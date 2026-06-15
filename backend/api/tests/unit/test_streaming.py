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


import pytest

@pytest.mark.skip(reason="Uses aioredis directly, requires integration test or complex mock")
def test_stream_task_result_delivers_message(monkeypatch):
    pass
