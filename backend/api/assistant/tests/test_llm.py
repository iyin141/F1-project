"""The headless runner with a fake subprocess: parsing, malformed-output retry, error classes, argv, streaming."""
import json

import pytest

from api.assistant import llm

SCHEMA = {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}


def ok_json(out, cost=0.001):
    return json.dumps({"type": "result", "is_error": False, "structured_output": out, "result": json.dumps(out),
                       "total_cost_usd": cost, "usage": {"input_tokens": 2}})


class FakeProc:
    created = []

    def __init__(self, argv, outs, cwd=None, **kw):
        self.argv, self.cwd = argv, cwd
        self.out, self.err, self.returncode = outs.pop(0)
        self.stdin = self
        self.stdout = iter(self.out.splitlines(keepends=True))
        self.stderr = self
        FakeProc.created.append(self)

    def communicate(self, input=None, timeout=None):
        self.stdin_text = input
        return self.out, self.err

    def write(self, text):
        self.stdin_text = text

    def close(self):
        pass

    def read(self):
        return self.err

    def wait(self):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        pass


@pytest.fixture
def popen(monkeypatch):
    outs = []
    FakeProc.created = []
    monkeypatch.setattr(llm.subprocess, "Popen", lambda argv, **kw: FakeProc(argv, outs, cwd=kw.get("cwd")))
    monkeypatch.setattr(llm, "resolve_claude_binary", lambda *a, **k: "claude")
    return outs


def runner():
    return llm.ClaudeRunner(sleep=lambda s: None)


# ---- parsing ----

def test_structured_output_is_preferred_and_result_text_is_the_fallback():
    assert llm.parse_json_result(ok_json({"action": "answer"}))["output"] == {"action": "answer"}
    legacy = json.dumps({"is_error": False, "result": '{"action": "tools"}'})
    assert llm.parse_json_result(legacy)["output"] == {"action": "tools"}


def test_error_payloads_are_classified():
    with pytest.raises(llm.RateLimited):
        llm.parse_json_result(json.dumps({"is_error": True, "result": "Claude usage limit reached"}))
    with pytest.raises(llm.AuthExpired):
        llm.parse_json_result(json.dumps({"is_error": True, "result": "Not logged in - please run /login"}))
    with pytest.raises(llm.BadOutput):
        llm.parse_json_result("not json at all")


# ---- plan(): retries and argv ----

def test_malformed_output_is_retried_once_then_succeeds(popen):
    popen += [("garbage{", "", 0), (ok_json({"action": "answer"}), "", 0)]
    assert runner().plan("q", "sys", SCHEMA) == {"action": "answer"}
    assert len(FakeProc.created) == 2


def test_malformed_output_twice_raises_bad_output(popen):
    popen += [("garbage{", "", 0), ("still garbage", "", 0), (ok_json({"action": "answer"}), "", 0)]
    with pytest.raises(llm.BadOutput):
        runner().plan("q", "sys", SCHEMA)
    assert len(FakeProc.created) == 2  # never a third try


def test_rate_limit_backs_off_and_retries_but_auth_is_never_retried(popen):
    popen += [("", "429 rate limit", 1), (ok_json({"action": "answer"}), "", 0)]
    assert runner().plan("q", "sys", SCHEMA) == {"action": "answer"}
    popen[:] = [("", "Not logged in", 1), (ok_json({"action": "answer"}), "", 0)]
    FakeProc.created.clear()
    with pytest.raises(llm.AuthExpired):
        runner().plan("q", "sys", SCHEMA)
    assert len(FakeProc.created) == 1


def test_argv_follows_the_contract(popen):
    popen.append((ok_json({"action": "answer"}), "", 0))
    runner().plan("the prompt", "the system", SCHEMA)
    p = FakeProc.created[0]
    a = p.argv
    assert a[:2] == ["claude", "-p"] and "--bare" not in a
    assert a[a.index("--output-format") + 1] == "json"
    assert json.loads(a[a.index("--json-schema") + 1]) == SCHEMA          # inline JSON, not a path
    assert a[a.index("--model") + 1] == llm.MODEL_PLANNER
    assert a[a.index("--append-system-prompt") + 1] == "the system"
    assert a[a.index("--tools") + 1] == "" and "--no-session-persistence" in a  # no built-in tools, nothing saved
    assert p.stdin_text == "the prompt"                                   # prompt on stdin, not argv
    assert "the prompt" not in a


def test_cwd_is_an_empty_temp_dir(popen):
    popen.append((ok_json({"action": "answer"}), "", 0))
    runner().plan("q", "s", SCHEMA)
    assert "stewards_claude_" in FakeProc.created[0].cwd


# ---- streaming ----

def stream_lines(*texts):
    ev = [{"type": "system", "subtype": "init"}]
    ev += [{"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": t}}} for t in texts]
    ev += [{"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "hmm"}}}]
    ev += [{"type": "result", "is_error": False, "result": "".join(texts), "total_cost_usd": 0.01}]
    return "\n".join(json.dumps(e) for e in ev) + "\n"


def test_stream_answer_yields_text_deltas_then_result(popen):
    popen.append((stream_lines("Hello", " world [E1]"), "", 0))
    r = runner()
    got = list(r.stream_answer("p", "s"))
    assert [v for k, v in got if k == "delta"] == ["Hello", " world [E1]"]   # thinking deltas are not forwarded
    assert got[-1] == ("result", {"text": "Hello world [E1]", "cost_usd": 0.01})
    a = FakeProc.created[0].argv
    assert a[a.index("--output-format") + 1] == "stream-json" and "--include-partial-messages" in a and "--verbose" in a
    assert r.cost_usd == pytest.approx(0.01)


def test_stream_without_result_line_raises(popen):
    popen.append(('{"type":"system"}\n', "Not logged in", 1))
    with pytest.raises(llm.AuthExpired):
        list(runner().stream_answer("p", "s"))


def test_resolve_binary_override_and_shim(tmp_path):
    assert llm.resolve_claude_binary({"CLAUDE_BINARY": "/x/claude"}) == "/x/claude"
    assert llm.resolve_claude_binary({}, which=lambda n: None) == "claude"
    assert llm.resolve_claude_binary({}, which=lambda n: "/usr/bin/claude") == "/usr/bin/claude"


def test_planner_runs_at_low_effort_and_answer_at_cli_default(popen, monkeypatch):
    popen.append((ok_json({"action": "answer"}), "", 0))
    runner().plan("q", "s", SCHEMA)
    a = FakeProc.created[0].argv
    assert a[a.index("--effort") + 1] == "low"
    popen.append((stream_lines("x"), "", 0))
    list(runner().stream_answer("p", "s"))
    assert "--effort" not in FakeProc.created[1].argv
