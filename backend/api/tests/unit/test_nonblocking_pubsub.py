import json
import api.services.pubsub as pubsub


def test_publish_result_and_error_calls_redis_publish(monkeypatch):
    calls = []

    class FakeClient:
        def publish(self, channel, message):
            calls.append((channel, message))

    # Replace the module-level client with our fake
    monkeypatch.setattr(pubsub, "redis_publish_client", FakeClient())

    pubsub.publish_result("task:1", {"value": 123})
    pubsub.publish_error("task:1", "boom")

    assert any(c[0] == "task_result:task:1" for c in calls)
    msgs = [json.loads(c[1]) for c in calls]
    assert any(m.get("status") == "complete" for m in msgs)
    assert any(m.get("status") == "failed" for m in msgs)


def test_subscribe_to_task_uses_redis_from_url(monkeypatch):
    # Ensure subscribe_to_task returns a pubsub-like object and calls subscribe
    subscribed = []

    class FakePub:
        def subscribe(self, channel):
            subscribed.append(channel)

    class FakeClient:
        def pubsub(self):
            return FakePub()

    monkeypatch.setattr(pubsub.redis, "from_url", lambda url, decode_responses=True: FakeClient())

    ps = pubsub.subscribe_to_task("tkey")
    assert hasattr(ps, "subscribe")
    assert subscribed == ["task_result:tkey"]
