"""
SSE streaming response for task result delivery.

Subscribes to a Redis pub/sub channel for a specific task_key and streams
the result back to the client as a Server-Sent Events response.

Compatible with Waitress (WSGI) — no async required.
"""
import json
import logging
import time

from django.http import StreamingHttpResponse

from api.services import pubsub as pubsub_service

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 40  # Wall-clock limit per stream


def stream_task_result(task_key: str) -> StreamingHttpResponse:
    """
    Return a StreamingHttpResponse (text/event-stream) that delivers the
    task result as a single SSE data frame once the worker publishes it.

    The generator subscribes to `task_result:{task_key}`, waits up to 40 s
    for the first message, then closes cleanly.
    """
    response = StreamingHttpResponse(
        _sse_generator(task_key),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def _sse_generator(task_key: str):
    """Generator that yields SSE-formatted frames from the pub/sub channel."""
    ps = pubsub_service.subscribe_to_task(task_key)
    logger.info("sse.subscribed task_key=%s", task_key)
    start = time.monotonic()

    try:
        for message in ps.listen():
            # Respect wall-clock timeout
            elapsed = time.monotonic() - start
            if elapsed >= _TIMEOUT_SECONDS:
                logger.warning("sse.timeout task_key=%s elapsed_ms=%d", task_key, int(elapsed * 1000))
                yield f"data: {json.dumps({'status': 'timeout', 'task_key': task_key})}\n\n"
                return

            # Skip subscription-confirmation and other non-data frames
            if message.get("type") != "message":
                continue

            # Parse the pub/sub message to extract the nested data payload
            raw_data = message.get("data", "")
            try:
                message_dict = json.loads(raw_data)
                # Extract only the 'data' field from the message if it exists
                payload = message_dict.get("data", message_dict)
                # If payload is dict, convert back to JSON string; if already string, use as-is
                if isinstance(payload, dict):
                    data_str = json.dumps(payload)
                else:
                    data_str = str(payload)
            except (json.JSONDecodeError, ValueError):
                # Fallback: use raw message if parsing fails
                data_str = raw_data

            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info("sse.result_delivered task_key=%s elapsed_ms=%d", task_key, elapsed_ms)
            yield f"data: {data_str}\n\n"
            return  # One result per stream — close immediately after delivery

        # Generator exhausted without a message (channel closed early)
        elapsed = time.monotonic() - start
        logger.warning("sse.timeout task_key=%s elapsed_ms=%d", task_key, int(elapsed * 1000))
        yield f"data: {json.dumps({'status': 'timeout', 'task_key': task_key})}\n\n"

    finally:
        try:
            ps.unsubscribe()
            ps.close()
        except Exception:
            pass
        logger.info("sse.closed task_key=%s", task_key)


def stream_task_result_json(task_key: str) -> StreamingHttpResponse:
    """
    Return a StreamingHttpResponse (application/json) that delivers the
    task result as a pure JSON string once the worker publishes it.
    This replaces the SSE wrapper to allow browsers to natively format the result.
    """
    response = StreamingHttpResponse(
        _json_generator(task_key),
        content_type="application/json",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def _json_generator(task_key: str):
    """Generator that yields the raw JSON string from the pub/sub channel without SSE formatting."""
    ps = pubsub_service.subscribe_to_task(task_key)
    logger.info("json_stream.subscribed task_key=%s", task_key)
    start = time.monotonic()

    try:
        for message in ps.listen():
            elapsed = time.monotonic() - start
            if elapsed >= _TIMEOUT_SECONDS:
                logger.warning("json_stream.timeout task_key=%s elapsed_ms=%d", task_key, int(elapsed * 1000))
                yield json.dumps({'status': 'timeout', 'task_key': task_key})
                return

            if message.get("type") != "message":
                continue

            raw_data = message.get("data", "")
            try:
                message_dict = json.loads(raw_data)
                payload = message_dict.get("data", message_dict)
                if isinstance(payload, dict) or isinstance(payload, list):
                    data_str = json.dumps(payload)
                else:
                    data_str = str(payload)
            except (json.JSONDecodeError, ValueError):
                data_str = raw_data

            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info("json_stream.result_delivered task_key=%s elapsed_ms=%d", task_key, elapsed_ms)
            # Yield purely the JSON string without the SSE "data: ... \n\n" wrapper
            yield data_str
            return

        elapsed = time.monotonic() - start
        logger.warning("json_stream.timeout task_key=%s elapsed_ms=%d", task_key, int(elapsed * 1000))
        yield json.dumps({'status': 'timeout', 'task_key': task_key})

    finally:
        try:
            ps.unsubscribe()
            ps.close()
        except Exception:
            pass
        logger.info("json_stream.closed task_key=%s", task_key)


def stream_combined_task_results_json(task_keys: list) -> StreamingHttpResponse:
    """
    Combines multiple task keys into a single pure JSON response.
    Waits for all tasks to finish, parses them, merges them, and yields the final JSON string.
    """
    response = StreamingHttpResponse(
        _combined_json_generator(task_keys),
        content_type="application/json",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def _combined_json_generator(task_keys: list):
    """Subscribes to multiple tasks and yields a single JSON string when all complete."""
    import redis
    from api.services.pubsub import REDIS_URL
    client = redis.from_url(REDIS_URL, decode_responses=True)
    ps = client.pubsub()
    channels = [f"task_result:{key}" for key in task_keys]
    for ch in channels:
        ps.subscribe(ch)

    logger.info("combined_json.subscribed channels=%s", channels)
    start = time.monotonic()
    
    results = {}
    pending_keys = set(task_keys)

    try:
        for message in ps.listen():
            elapsed = time.monotonic() - start
            if elapsed >= _TIMEOUT_SECONDS:
                logger.warning("combined_json.timeout pending=%s", pending_keys)
                yield json.dumps({'status': 'timeout'})
                return

            if message.get("type") != "message":
                continue

            channel_b = message.get("channel")
            channel = channel_b.decode('utf-8') if isinstance(channel_b, bytes) else str(channel_b)
            task_key = channel.replace("task_result:", "")

            if task_key not in pending_keys:
                continue

            raw_data = message.get("data", "")
            try:
                msg_dict = json.loads(raw_data)
                payload = msg_dict.get("data", msg_dict)
                results[task_key] = payload
            except (json.JSONDecodeError, ValueError):
                pass
            
            pending_keys.remove(task_key)

            if not pending_keys:
                break

        # All tasks finished. Merge them!
        # Find the primary session payload (Race or Sprint)
        main_payload = None
        qual_payload = []
        
        for key, payload in results.items():
            if "race_results" in key:
                main_payload = payload
            elif "qualifying" in key:
                if isinstance(payload, dict):
                    qual_payload = payload.get("data", [])
                elif isinstance(payload, list):
                    qual_payload = payload
                else:
                    qual_payload = []

        if main_payload and isinstance(main_payload, dict):
            # Inject qualifying data into the main payload's root level
            main_payload["qualifying"] = qual_payload
            
            # Ensure "qualifying_results" is in available_data if we have it
            meta = main_payload.get("meta", {})
            if meta and qual_payload:
                avail = meta.get("available_data", [])
                if "qualifying_results" not in avail:
                    avail.append("qualifying_results")
                unavail = meta.get("unavailable_data", [])
                if "qualifying_results" in unavail:
                    unavail.remove("qualifying_results")
                
                # Clear the warning message since qualifying data arrived
                if meta.get("message") == "Qualifying data not yet available.":
                    meta["message"] = None
                
            final_json = json.dumps(main_payload)
        else:
            final_json = json.dumps(results)

        yield final_json

    finally:
        try:
            ps.unsubscribe()
            ps.close()
        except Exception:
            pass
        logger.info("combined_json.closed")
