"""
View cache integration — Phase 4: Decorator for write-through cache and SETNX locks.

Provides a @cached_view decorator that wraps endpoints to:
1. Check Redis cache → return 200
2. Check DB → backfill Redis → return 200
3. Check in-flight lock → return 202 with existing task ID
4. Enqueue task + set lock → return 202 with new task ID
"""
from __future__ import annotations

import functools
import logging
from typing import Callable, Optional, Any, Type

from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework import status

from .cache_service import (
    get_from_cache,
    set_cache,
    check_load_lock,
    set_load_lock,
    release_load_lock,
    get_cache_ttl,
    get_load_lock_ttl,
)
from .queue.manager import TaskManager

logger = logging.getLogger(__name__)


def cached_view(
    data_type: str,
    task_function: Optional[Callable] = None,
    task_args_resolver: Optional[Callable] = None,
):
    """
    Decorator for DRF views to implement write-through cache + SETNX locks.
    
    Usage:
        @cached_view(
            data_type="standings",
            task_function=populate_standings,  # Celery task
            task_args_resolver=lambda year, round: (year, round)
        )
        def standings_view(request, year, round):
            ...
            
    Args:
        data_type: Type of data being cached (e.g., "standings", "weather")
        task_function: Optional Celery task to enqueue on cache miss
        task_args_resolver: Function to extract (year, round, session) from view arguments
    """
    def decorator(view_func: Callable):
        @functools.wraps(view_func)
        def wrapper(self, request, *args, **kwargs):
            # Extract session identifiers from view arguments
            # Typically: view_url_patterns like races/<int:year>/<int:round>/results/
            year = kwargs.get("year") or args[0] if args else None
            round_number = kwargs.get("round") or args[1] if len(args) > 1 else None
            session = kwargs.get("session", "R")  # Default to Race
            
            if year is None or round_number is None:
                # Missing required parameters; fall through to view
                return view_func(self, request, *args, **kwargs)
            
            # Step 1: Check cache chain (Redis → DB)
            db_queryset = getattr(self, 'get_queryset', lambda: None)()
            cached_data, source = get_from_cache(
                data_type=data_type,
                year=year,
                round_number=round_number,
                session=session,
                model_queryset=db_queryset,
            )
            
            if cached_data is not None:
                # Cache hit! Return 200
                logger.info(
                    "[CachedView] Cache hit data_type=%s year=%s round=%s source=%s",
                    data_type, year, round_number, source,
                )
                return Response(cached_data, status=status.HTTP_200_OK)
            
            # Step 2: Cache miss — check for in-flight load
            existing_task_id = check_load_lock(
                data_type=data_type,
                year=year,
                round_number=round_number,
                session=session,
            )
            
            if existing_task_id is not None:
                # Load already in progress — return 202 with existing task
                logger.info(
                    "[CachedView] Load in progress (existing lock) data_type=%s year=%s round=%s task_id=%s",
                    data_type, year, round_number, existing_task_id,
                )
                return Response(
                    {
                        "status": "queued",
                        "task_id": existing_task_id,
                        "message": "Load already in progress; reusing existing task",
                    },
                    status=status.HTTP_202_ACCEPTED,
                )
            
            # Step 3: Enqueue new task + set lock
            if task_function is not None:
                task_key = f"{data_type}:{year}:{round_number}:{session}"
                task_args = task_args_resolver(year, round_number, session) if task_args_resolver else (year, round_number, session)
                
                # Dispatch task via TaskManager (includes queue routing and Redis SETNX lock)
                success = TaskManager.enqueue_if_needed(
                    task_key=task_key,
                    task_fn=task_function,
                    *task_args,
                )
                
                if success:
                    # Get the celery task ID for polling
                    # Note: In production, TaskManager should return AsyncResult
                    # For now, return a generated task key
                    logger.info(
                        "[CachedView] Task enqueued data_type=%s year=%s round=%s task_key=%s",
                        data_type, year, round_number, task_key,
                    )
                    return Response(
                        {
                            "status": "queued",
                            "task_id": task_key,
                            "message": "Data load queued; check status endpoint for completion",
                        },
                        status=status.HTTP_202_ACCEPTED,
                    )
                else:
                    logger.warning(
                        "[CachedView] Task dispatch failed data_type=%s year=%s round=%s",
                        data_type, year, round_number,
                    )
                    return Response(
                        {"error": "Failed to queue task"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
            
            # No task function provided; call view directly (fallback)
            return view_func(self, request, *args, **kwargs)
        
        return wrapper
    return decorator


def cache_response(data_type: str, timeout: Optional[int] = None):
    """
    Decorator to cache a view response in Redis.
    
    Usage:
        @cache_response("standings", timeout=3600)
        def standings_view(request):
            return Response(data)
    """
    def decorator(view_func: Callable):
        @functools.wraps(view_func)
        def wrapper(*args, **kwargs):
            result = view_func(*args, **kwargs)
            
            # Extract year/round from kwargs if available
            year = kwargs.get("year")
            round_number = kwargs.get("round")
            session = kwargs.get("session", "R")
            
            if year and round_number and hasattr(result, 'data'):
                # Cache the response data
                ttl = timeout or get_cache_ttl(data_type)
                set_cache(
                    data_type=data_type,
                    year=year,
                    round_number=round_number,
                    session=session,
                    data=result.data,
                    timeout=ttl,
                )
            
            return result
        
        return wrapper
    return decorator


class CachedViewMixin:
    """
    Mixin for DRF views to add write-through caching automatically.
    
    Subclass must define:
    - cache_data_type: str (e.g., "standings")
    - cache_task_function: Celery task (optional)
    - cache_task_args_resolver: Callable to extract task args (optional)
    
    Usage:
        class StandingsView(CachedViewMixin, generics.RetrieveAPIView):
            cache_data_type = "standings"
            cache_task_function = populate_standings
            
            def get_queryset(self):
                return ConstructorStandings.objects.all()
    """
    
    cache_data_type: str = None
    cache_task_function: Optional[Callable] = None
    cache_task_args_resolver: Optional[Callable] = None
    
    def get(self, request, *args, **kwargs):
        """
        Override GET to add caching layer.
        """
        if self.cache_data_type is None:
            # No caching configured; call parent
            return super().get(request, *args, **kwargs)
        
        # Extract session identifiers
        year = kwargs.get("year") or args[0] if args else None
        round_number = kwargs.get("round") or args[1] if len(args) > 1 else None
        session = kwargs.get("session", "R")
        
        if year is None or round_number is None:
            # Missing required params; proceed without caching
            return super().get(request, *args, **kwargs)
        
        # Step 1: Check cache chain
        queryset = self.get_queryset()
        cached_data, source = get_from_cache(
            data_type=self.cache_data_type,
            year=year,
            round_number=round_number,
            session=session,
            model_queryset=queryset,
        )
        
        if cached_data is not None:
            logger.info(
                "[CachedViewMixin] Cache hit data_type=%s year=%s round=%s source=%s",
                self.cache_data_type, year, round_number, source,
            )
            return Response(cached_data, status=status.HTTP_200_OK)
        
        # Step 2: Check in-flight lock
        existing_task_id = check_load_lock(
            data_type=self.cache_data_type,
            year=year,
            round_number=round_number,
            session=session,
        )
        
        if existing_task_id is not None:
            logger.info(
                "[CachedViewMixin] Load in progress data_type=%s year=%s round=%s task_id=%s",
                self.cache_data_type, year, round_number, existing_task_id,
            )
            return Response(
                {
                    "status": "queued",
                    "task_id": existing_task_id,
                },
                status=status.HTTP_202_ACCEPTED,
            )
        
        # Step 3: Enqueue task
        if self.cache_task_function is not None:
            task_key = f"{self.cache_data_type}:{year}:{round_number}:{session}"
            task_args = self.cache_task_args_resolver(year, round_number, session) if self.cache_task_args_resolver else (year, round_number, session)
            
            success = TaskManager.enqueue_if_needed(
                task_key=task_key,
                task_fn=self.cache_task_function,
                *task_args,
            )
            
            if success:
                return Response(
                    {"status": "queued", "task_id": task_key},
                    status=status.HTTP_202_ACCEPTED,
                )
        
        # Fall through to parent view
        return super().get(request, *args, **kwargs)
