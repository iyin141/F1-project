import json

from api.services import streaming


class FakePS:
    def __init__(self, messages):
        self._messages = list(messages)

    def listen(self):
        for m in self._messages:
            yield m

    def unsubscribe(self):
        pass

    def close(self):
        pass


def test_stream_task_result_delivers_message(monkeypatch):
    # Provide a fake pubsub that yields a single message frame
    msg = {"type": "message", "data": json.dumps({"status": "complete", "x": 1})}
    monkeypatch.setattr(
        "api.services.pubsub.subscribe_to_task",
        lambda task_key: FakePS([msg]),
    )

    # Call the internal generator directly to avoid Django response charset/settings
    gen = streaming._sse_generator("task:abc")
    parts = list(gen)
    body = "".join(parts)
    assert "status" in body and "complete" in body
