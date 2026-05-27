# Module S: Non-blocking View Pattern — IMPLEMENTATION PLAN

**Objective**: Implement 4-step async pattern for 16 time-intensive views returning 202 Accepted with task tracking.

## 16 Views Requiring Non-blocking Pattern

### Analysis Views (8 views)

1. `AnalysisLapsAPIView` - Lap analysis data (time-intensive per-driver aggregation)
2. `AnalysisStintsAPIView` - Stint analysis (time-intensive per-driver aggregation)
3. `AnalysisPaceAPIView` - Pace analysis (time-intensive calculation)
4. `AnalysisSectorAPIView` - Sector analysis (time-intensive time calculation)
5. `AnalysisTelemetryAPIView` - Telemetry processing (time-intensive download + processing)
6. `AnalysisTelemetryOverlayAPIView` - Telemetry overlay (time-intensive data correlation)
7. `UnifiedFullSessionAPIView` - Full session data aggregation (time-intensive)
8. `UnifiedWeatherAPIView` - Weather aggregation (time-intensive)

### Driver Views (2 views)

9. `DriverCareerAPIView` - Driver career aggregation (time-intensive across seasons)
10. `DriverSeasonAPIView` - Driver season breakdown (time-intensive per-season aggregation)

### Unified/Results Views (6 views)

11. `UnifiedPitStopsAPIView` - Pit stop data (medium latency)
12. `UnifiedIncidentsAPIView` - Incident aggregation (time-intensive)
13. `UnifiedPositionsAPIView` - Position history (time-intensive)
14. `UnifiedDRSAPIView` - DRS usage tracking (time-intensive)
15. `UnifiedTrackStatusAPIView` - Track status aggregation (time-intensive)
16. `ConstructorStandingsAPIView` - Constructor standings (medium latency, pagination)

---

## 4-Step Non-blocking Pattern

### Step 1: Check if Task Already Running

```python
task_key = f"{endpoint_type}:{year}:{round}:{extras}"
existing_task = TaskManager.get_status(task_key)

if existing_task and existing_task['status'] in ['pending', 'running']:
    # Task already running - return 202 with task_id
    return Response(
        {
            'message': 'Data processing in progress',
            'task_id': existing_task['id'],
            'status_url': f'/api/tasks/{existing_task["id"]}/status/'
        },
        status=202
    )
```

### Step 2: Start New Task if Needed

```python
if not existing_task:
    # Start new background task
    task = async_populate_analysis_laps.apply_async(
        args=[year, round_number],
        task_id=task_key,
        queue='tier2_fast'
    )

    TaskManager.mark_running(task_key, task.id)

    return Response(
        {
            'message': 'Data processing started',
            'task_id': task.id,
            'status_url': f'/api/tasks/{task.id}/status/',
            'poll_interval_seconds': 5
        },
        status=202
    )
```

### Step 3: Check Cache if Task Complete

```python
# If task is done, check Redis cache for result
if existing_task and existing_task['status'] == 'complete':
    cached_data = get_from_cache(
        build_cache_key(year, round, session, 'laps')
    )

    if cached_data:
        return Response(json.loads(cached_data), status=200)
```

### Step 4: Polling Endpoint

```python
# GET /api/tasks/{task_id}/status/
# Returns: {"status": "pending|running|complete|failed", "progress": 0-100}

@api_view(['GET'])
def get_task_status(request, task_id):
    status = TaskManager.get_status(task_id)

    return Response({
        'task_id': task_id,
        'status': status['status'],
        'progress': status.get('progress', 0),
        'message': status.get('message', ''),
        'result_url': f'/api/{endpoint}/{year}/{round}/' if status['status'] == 'complete' else None
    })
```

---

## Implementation Approach

### A. Create Task-aware Mixin

```python
# api/common/mixins.py - add new class

class NonBlockingAPIMixin:
    """
    Implements 4-step async pattern for time-intensive endpoints.

    Subclass must define:
    - task_key_format: str template for task key
    - async_task_name: str Celery task name
    - queue: str queue name (tier2_fast, tier3_medium, etc.)
    """

    def get_or_start_task(self, request, **kwargs) -> Response:
        """Returns either 202 + task_id or 200 + cached data"""

        # Step 1: Build task key
        task_key = self.build_task_key(**kwargs)

        # Step 2: Check if running
        status = TaskManager.get_status(task_key)
        if status and status['status'] in ['pending', 'running']:
            return self.task_pending_response(task_key, status)

        # Step 3: Start if needed
        if not status:
            task = self.start_async_task(**kwargs)
            TaskManager.mark_running(task_key, task.id)
            return self.task_started_response(task_key, task.id)

        # Step 4: If complete, return data
        if status['status'] == 'complete':
            return self.get_completed_data(**kwargs)

        return Response({'error': 'Unknown task state'}, status=500)

    def build_task_key(self, **kwargs) -> str:
        """Override in subclass"""
        raise NotImplementedError

    def start_async_task(self, **kwargs):
        """Override in subclass"""
        raise NotImplementedError
```

### B. Update All 16 Views to Use Mixin

```python
# Example: AnalysisLapsAPIView

class AnalysisLapsAPIView(NonBlockingAPIMixin, RateLimitHeadersMixin, APIView):
    permission_classes = [APIKeyAuthentication]
    throttle_classes = [APIKeyThrottle]

    def get(self, request, year, round_number):
        """
        GET /api/analysis/{year}/{round}/laps/

        Returns:
        - 200: {"data": [...]} if cached
        - 202: {"task_id": "...", "status_url": "..."} if processing
        """
        return self.get_or_start_task(request, year=year, round_number=round_number)

    def build_task_key(self, **kwargs) -> str:
        return f"laps:{kwargs['year']}:{kwargs['round_number']}"

    def start_async_task(self, **kwargs):
        return async_populate_analysis_laps.apply_async(
            args=[kwargs['year'], kwargs['round_number']],
            queue='tier3_medium'
        )

    def get_completed_data(self, **kwargs):
        cache_key = build_cache_key(
            kwargs['year'], kwargs['round_number'], 'analysis', 'laps'
        )
        data = get_from_cache(cache_key)
        if data:
            return Response(json.loads(data) if isinstance(data, str) else data)
        return Response({'error': 'Data not found'}, status=404)
```

### C. Create Polling Endpoint

```python
# In api/views.py (or new api/views/tasks.py)

class TaskStatusAPIView(APIView):
    """GET /api/tasks/{task_id}/status/"""
    permission_classes = [APIKeyAuthentication]

    def get(self, request, task_id):
        status = TaskManager.get_status(task_id)

        if not status:
            return Response({'error': 'Task not found'}, status=404)

        return Response({
            'task_id': task_id,
            'status': status['status'],
            'progress': status.get('progress', 0),
            'message': status.get('message', ''),
            'started_at': status.get('started_at'),
            'completed_at': status.get('completed_at') if status['status'] == 'complete' else None
        })
```

### D. Update TaskManager

```python
# api/services/task_manager.py - add methods

class TaskManager:

    @staticmethod
    def get_status(task_key: str) -> Optional[dict]:
        """Get task status from Redis"""
        cache_key = f"task:{task_key}"
        return cache.get(cache_key)  # Returns None if not found

    @staticmethod
    def mark_running(task_key: str, celery_task_id: str):
        """Mark task as running"""
        cache_key = f"task:{task_key}"
        cache.set(cache_key, {
            'status': 'running',
            'id': celery_task_id,
            'started_at': datetime.now().isoformat(),
            'progress': 0
        }, ttl=ttl_for('task_status', datetime.now().year))

    @staticmethod
    def update_progress(task_key: str, progress: int, message: str = ''):
        """Update task progress (0-100)"""
        cache_key = f"task:{task_key}"
        current = cache.get(cache_key) or {}
        current.update({
            'progress': min(100, max(0, progress)),
            'message': message
        })
        cache.set(cache_key, current, ttl=600)  # 10 min
```

### E. Add URLs for Polling Endpoint

```python
# api/urls.py - add

urlpatterns = [
    # ... existing paths ...
    path('tasks/<str:task_id>/status/', views.TaskStatusAPIView.as_view(), name='task-status'),
]
```

---

## Response Examples

### Starting Task (202)

```json
{
  "message": "Data processing started",
  "task_id": "laps:2024:1",
  "status_url": "/api/tasks/laps:2024:1/status/",
  "poll_interval_seconds": 5
}
```

### Task Running (202)

```json
{
  "message": "Data processing in progress",
  "task_id": "laps:2024:1",
  "status_url": "/api/tasks/laps:2024:1/status/"
}
```

### Task Status (200)

```json
{
  "task_id": "laps:2024:1",
  "status": "running",
  "progress": 45,
  "message": "Processing driver LAP data...",
  "started_at": "2024-11-15T10:30:00"
}
```

### Complete (200)

```json
{
  "task_id": "laps:2024:1",
  "status": "complete",
  "progress": 100,
  "started_at": "2024-11-15T10:30:00",
  "completed_at": "2024-11-15T10:35:30"
}
```

### Data Ready (200)

```json
{
  "data": [
    {
      "driver_code": "VER",
      "lap_count": 42,
      "avg_lap_time": "1:24.532",
      "fastest_lap": "1:23.201"
    }
  ]
}
```

---

## Files to Create/Modify

| File                         | Changes                             | Priority |
| ---------------------------- | ----------------------------------- | -------- |
| api/common/mixins.py         | Add `NonBlockingAPIMixin`           | HIGH     |
| api/views.py                 | Update 16 views to use mixin        | HIGH     |
| api/views.py                 | Add `TaskStatusAPIView`             | HIGH     |
| api/services/task_manager.py | Add status tracking methods         | HIGH     |
| api/urls.py                  | Add `/api/tasks/{id}/status/` route | HIGH     |
| api/common/response.py       | Document 202 responses in schema    | MEDIUM   |

---

## Testing Strategy

1. **Unit Tests**: Mock TaskManager.get_status() to test 202/200 flow
2. **Integration Tests**: Start real Celery task, poll endpoint, verify transition
3. **Load Tests**: Verify race conditions (duplicate task starts) don't occur
4. **E2E Tests**: Client SDK implements 202 polling flow

---

## Client Implementation Pattern

```javascript
// JavaScript/Next.js frontend example

async function pollAnalysisData(year, round) {
  const response = await fetch(`/api/analysis/${year}/${round}/laps/`);

  if (response.status === 202) {
    const data = await response.json();
    const taskId = data.task_id;

    // Poll every 5 seconds
    while (true) {
      const statusResponse = await fetch(`/api/tasks/${taskId}/status/`);
      const status = await statusResponse.json();

      if (status.status === "complete") {
        // Retry original request - now will return 200 + cached data
        return fetch(`/api/analysis/${year}/${round}/laps/`);
      }

      console.log(`Progress: ${status.progress}%`);
      await new Promise((r) => setTimeout(r, 5000));
    }
  }

  return response.json();
}
```

---

## Benefits

✅ **User Experience**: Clients get immediate 202 response instead of hanging  
✅ **Server Load**: Long requests don't block connection pool  
✅ **Idempotency**: Multiple requests for same data reuse running task  
✅ **Observability**: Client can poll progress + ETA  
✅ **Resilience**: Task can retry internally without client awareness

---

**Next Steps**: Implement changes in this order:

1. Create NonBlockingAPIMixin
2. Update TaskManager with status tracking
3. Update all 16 views
4. Add TaskStatusAPIView + route
5. Document in OpenAPI schema
