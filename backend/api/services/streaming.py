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
