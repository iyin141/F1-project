"""
Redis pub/sub client for SSE task result delivery.

Uses a raw redis-py client (independent of Django's cache framework) so that
publish/subscribe operations are fully supported. Both clients target REDIS_1_URL
(the app cache Redis instance, DB 1) — no new env vars required.
"""
import json
import logging

import redis
from decouple import config

logger = logging.getLogger(__name__)

REDIS_URL = config("REDIS_1_URL", default="redis://127.0.0.1:6379/1")

# Shared connection pool for publishing (reused across requests)
_publish_pool = redis.ConnectionPool.from_url(REDIS_URL, decode_responses=True)
redis_publish_client = redis.StrictRedis(connection_pool=_publish_pool)


def _channel(task_key: str) -> str:
    return f"task_result:{task_key}"


def publish_result(task_key: str, payload: dict) -> None:
    """
    Publish a successful task result to the task's pub/sub channel.

    Workers call this immediately after writing data to cache/DB, before
    updating TaskRecord to 'complete'.
    """
    try:
        message = json.dumps({"status": "complete", **payload})
        redis_publish_client.publish(_channel(task_key), message)
        logger.debug("pubsub.publish task_key=%s", task_key)
    except Exception as exc:
        logger.error("pubsub.publish_failed task_key=%s error=%s", task_key, exc)


def publish_error(task_key: str, error: str) -> None:
    """Publish a failure notification to the task's pub/sub channel."""
    try:
        message = json.dumps({"status": "failed", "error": error})
        redis_publish_client.publish(_channel(task_key), message)
        logger.debug("pubsub.publish_error task_key=%s", task_key)
    except Exception as exc:
        logger.error("pubsub.publish_failed task_key=%s error=%s", task_key, exc)


def subscribe_to_task(task_key: str) -> redis.client.PubSub:
    """
    Subscribe to a task's result channel.

    Each call creates a fresh single-use redis connection (not from the shared
    pool) so that subscribe/listen can block independently per SSE stream.

    Caller is responsible for calling pubsub.unsubscribe() and closing the
    underlying connection when done.
    """
    client = redis.from_url(REDIS_URL, decode_responses=True)
    pubsub = client.pubsub()
    pubsub.subscribe(_channel(task_key))
    return pubsub
