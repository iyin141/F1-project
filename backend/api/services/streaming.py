"""
SSE streaming response for task result delivery.

Subscribes to a Redis pub/sub channel for a specific task_key and streams
the result back to the client as a Server-Sent Events response.

Compatible with ASGI (Uvicorn). Uses async/await to prevent blocking worker threads.
"""
import json
import logging
import time
import asyncio

from django.http import StreamingHttpResponse
import redis.asyncio as aioredis
from api.services.pubsub import REDIS_URL

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 40  # Wall-clock limit per stream


def stream_task_result(task_key: str) -> StreamingHttpResponse:
    """
    Return a StreamingHttpResponse (text/event-stream) that delivers the
    task result as a single SSE data frame once the worker publishes it.
    """
    response = StreamingHttpResponse(
        _sse_generator(task_key),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


async def _sse_generator(task_key: str):
    """Generator that yields SSE-formatted frames from the pub/sub channel asynchronously."""
    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    async with client.pubsub() as ps:
        await ps.subscribe(f"task_result:{task_key}")
        logger.info("sse.subscribed task_key=%s", task_key)
        start = time.monotonic()

        try:
            while True:
                elapsed = time.monotonic() - start
                if elapsed >= _TIMEOUT_SECONDS:
                    logger.warning("sse.timeout task_key=%s elapsed_ms=%d", task_key, int(elapsed * 1000))
                    yield f"data: {json.dumps({'status': 'timeout', 'task_key': task_key})}\n\n"
                    break

                try:
                    message = await asyncio.wait_for(ps.get_message(ignore_subscribe_messages=True), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if not message:
                    await asyncio.sleep(0.1)
                    continue

                if message.get("type") != "message":
                    continue

                raw_data = message.get("data", "")
                try:
                    message_dict = json.loads(raw_data)
                    payload = message_dict.get("data", message_dict)
                    if isinstance(payload, dict):
                        data_str = json.dumps(payload)
                    else:
                        data_str = str(payload)
                except (json.JSONDecodeError, ValueError):
                    data_str = raw_data

                elapsed_ms = int((time.monotonic() - start) * 1000)
                logger.info("sse.result_delivered task_key=%s elapsed_ms=%d", task_key, elapsed_ms)
                yield f"data: {data_str}\n\n"
                break
        finally:
            try:
                await ps.unsubscribe()
                await client.aclose()
            except Exception:
                logger.warning("Failed to close pubsub connection")
            logger.info("sse.closed task_key=%s", task_key)


def stream_task_result_json(task_key: str, timeout: int = _TIMEOUT_SECONDS) -> StreamingHttpResponse:
    """
    Return a StreamingHttpResponse (application/json) that delivers the
    task result as a pure JSON string once the worker publishes it.
    """
    response = StreamingHttpResponse(
        _json_generator(task_key, timeout),
        content_type="application/json",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


async def _json_generator(task_key: str, timeout: int):
    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    async with client.pubsub() as ps:
        await ps.subscribe(f"task_result:{task_key}")
        logger.info("json_stream.subscribed task_key=%s", task_key)
        start = time.monotonic()

        try:
            while True:
                elapsed = time.monotonic() - start
                if elapsed >= timeout:
                    logger.warning("json_stream.timeout task_key=%s elapsed_ms=%d", task_key, int(elapsed * 1000))
                    yield json.dumps({'status': 'timeout', 'task_key': task_key})
                    break

                try:
                    message = await asyncio.wait_for(ps.get_message(ignore_subscribe_messages=True), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if not message:
                    await asyncio.sleep(0.1)
                    continue

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
                yield data_str
                break
        finally:
            try:
                await ps.unsubscribe()
                await client.aclose()
            except Exception:
                logger.warning("Failed to close pubsub connection")
            logger.info("json_stream.closed task_key=%s", task_key)


def stream_combined_task_results_json(task_keys: list) -> StreamingHttpResponse:
    """Combines multiple task keys into a single pure JSON response."""
    response = StreamingHttpResponse(
        _combined_json_generator(task_keys),
        content_type="application/json",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


async def _combined_json_generator(task_keys: list):
    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    async with client.pubsub() as ps:
        channels = [f"task_result:{key}" for key in task_keys]
        for ch in channels:
            await ps.subscribe(ch)

        logger.info("combined_json.subscribed channels=%s", channels)
        start = time.monotonic()
        
        results = {}
        pending_keys = set(task_keys)

        try:
            while True:
                elapsed = time.monotonic() - start
                if elapsed >= _TIMEOUT_SECONDS:
                    logger.warning("combined_json.timeout pending=%s", pending_keys)
                    yield json.dumps({'status': 'timeout'})
                    break

                try:
                    message = await asyncio.wait_for(ps.get_message(ignore_subscribe_messages=True), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if not message:
                    await asyncio.sleep(0.1)
                    continue

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

            if pending_keys:
                return

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
                main_payload["qualifying"] = qual_payload
                meta = main_payload.get("meta", {})
                if meta and qual_payload:
                    avail = meta.get("available_data", [])
                    if "qualifying_results" not in avail:
                        avail.append("qualifying_results")
                    unavail = meta.get("unavailable_data", [])
                    if "qualifying_results" in unavail:
                        unavail.remove("qualifying_results")
                    if meta.get("message") == "Qualifying data not yet available.":
                        meta["message"] = None
                    
                final_json = json.dumps(main_payload)
            else:
                final_json = json.dumps(results)

            yield final_json

        finally:
            try:
                await ps.unsubscribe()
                await client.aclose()
            except Exception:
                logger.warning("Failed to close pubsub connection")
            logger.info("combined_json.closed")


def stream_unified_full_session_json(task_keys: list, include_types: list, base_meta: dict, timeout: int = _TIMEOUT_SECONDS) -> StreamingHttpResponse:
    """Subscribes to multiple Unified extractors and merges them into a single response."""
    response = StreamingHttpResponse(
        _unified_full_session_generator(task_keys, include_types, base_meta, timeout),
        content_type="application/json",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


async def _unified_full_session_generator(task_keys: list, include_types: list, base_meta: dict, timeout: int):
    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    async with client.pubsub() as ps:
        channels = [f"task_result:{key}" for key in task_keys]
        if channels:
            for ch in channels:
                await ps.subscribe(ch)

        logger.info("unified_full_session.subscribed channels=%s", channels)
        start = time.monotonic()
        
        results = {}
        pending_keys = set(task_keys)

        try:
            if not pending_keys:
                final_payload = {"meta": base_meta, "data": {}}
                yield json.dumps(final_payload)
                return

            while True:
                elapsed = time.monotonic() - start
                if elapsed >= timeout:
                    logger.warning("unified_full_session.timeout pending=%s", pending_keys)
                    base_meta["message"] = "Stream timed out waiting for background workers."
                    base_meta["warnings"].append(base_meta["message"])
                    for k in pending_keys:
                        results[k] = {"error": "Stream timeout", "status": "failed"}
                    break

                try:
                    message = await asyncio.wait_for(ps.get_message(ignore_subscribe_messages=True), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if not message:
                    await asyncio.sleep(0.1)
                    continue

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
                    data_type = task_key.split(":")[0].replace("populate_", "")
                    results[data_type] = payload
                except (json.JSONDecodeError, ValueError):
                    pass
                
                pending_keys.remove(task_key)

                if not pending_keys:
                    break

            available = []
            unavailable = []
            final_data = {}
            for data_type in include_types:
                if data_type in results:
                    res = results[data_type]
                    if isinstance(res, list):
                        final_data[data_type] = {"meta": {"row_count": len(res)}, "data": res}
                    else:
                        final_data[data_type] = res
                    
                    if isinstance(res, dict) and res.get("status") == "failed":
                        unavailable.append(data_type)
                    else:
                        available.append(data_type)
                else:
                    unavailable.append(data_type)
                    final_data[data_type] = {"error": "Not fetched", "status": "failed"}
                    
            base_meta["available_data"] = available
            base_meta["unavailable_data"] = unavailable
            base_meta["can_proceed"] = len(available) > 0
            
            final_payload = {"meta": base_meta, "data": final_data}
            yield json.dumps(final_payload)

        finally:
            try:
                await ps.unsubscribe()
                await client.aclose()
            except Exception:
                logger.warning("Failed to close pubsub connection")
            logger.info("unified_full_session.closed")
