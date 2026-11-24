"""Claude headless runner: the `claude` CLI run as a subprocess on the logged-in subscription (no API key).

Reimplemented (not imported) from the reference RAG pipeline's claude_headless.py. Flags verified against
`claude --help` of Claude Code 2.1.305 on this machine, and against two live calls (see progress file):

  -p                              print mode, prompt on stdin
  --output-format json            one JSON object: `structured_output` (parsed, when --json-schema is given),
                                  `result` (the same as text), `is_error`, `total_cost_usd`, `usage`, `modelUsage`
  --output-format stream-json --verbose --include-partial-messages
                                  one JSON object per line; token deltas are
                                  {"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":..}}},
                                  the last line is {"type":"result",...} with the full text and cost
  --json-schema <inline json>     structured output (inline string, not a file)
  --model <id>                    full model id, not an alias
  --append-system-prompt <text>   inline text (there is no -file variant)
  --tools ""                      no built-in tools: this is a text-in, text-out call, never an agent with Bash/Read
  --no-session-persistence        nothing saved to disk
  --disable-slash-commands --safe-mode
                                  no skills, hooks, CLAUDE.md or MCP servers from the host user's setup
  never --bare                    (it ignores the subscription login)

cwd is an empty temp dir. Errors are classified: rate limit (retried with backoff), auth expired (never retried),
bad JSON (retried once), timeout (retried once). Tests use `FakeRunner` and never start a process.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)

MODEL_PLANNER = os.environ.get("STEWARDS_PLANNER_MODEL", "claude-haiku-5-5")
MODEL_ANSWER = os.environ.get("STEWARDS_ANSWER_MODEL", "claude-sonnet-5-5")
MAX_STDIN_BYTES = 2 * 1024 * 1024
BASE_FLAGS = ["--tools", "", "--no-session-persistence", "--disable-slash-commands", "--safe-mode"]


class ClaudeError(Exception):
    pass


class RateLimited(ClaudeError):
    pass


class AuthExpired(ClaudeError):
    pass


class BadOutput(ClaudeError):
    pass


class ClaudeTimeout(ClaudeError):
    pass


def resolve_claude_binary(env=None, which: Callable[[str], str | None] = shutil.which) -> str:
    """The real claude executable. On Windows `npm i -g` leaves a .cmd shim that cannot carry our argv safely
    (cmd.exe quoting and length limits), so look for claude.exe next to it. CLAUDE_BINARY overrides."""
    env = os.environ if env is None else env
    if env.get("CLAUDE_BINARY"):
        return env["CLAUDE_BINARY"]
    found = which("claude")
    if not found:
        return "claude"
    if found.lower().endswith(".exe") or os.name != "nt":
        return found
    real = os.path.join(os.path.dirname(found), "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe")
    return real if os.path.isfile(real) else found


def classify(text: str, code: int = 1) -> ClaudeError:
    t = text.lower()
    if "rate limit" in t or "usage limit" in t or "429" in t or "overloaded" in t:
        return RateLimited(f"claude reported a rate/usage limit (exit {code})")
    if "not logged in" in t or "please run /login" in t or "unauthorized" in t or "401" in t or "authentication" in t:
        return AuthExpired("the claude login needs renewing (run `claude` and /login on this host)")
    return ClaudeError(f"claude exited {code}: {text[-600:]}")


def _argv(model: str, system: str, extra: list[str]) -> list[str]:
    return [resolve_claude_binary(), "-p", *extra, "--model", model, "--append-system-prompt", system, *BASE_FLAGS]


def parse_json_result(stdout: str) -> dict:
    """The `--output-format json` object -> the structured output. Raises BadOutput / classified errors."""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise BadOutput(f"stdout was not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise BadOutput("stdout JSON was not an object")
    if payload.get("is_error"):
        raise classify(f"{payload.get('result', '')} {payload.get('api_error_status', '')}")
    out = payload.get("structured_output")
    if out is None:
        res = payload.get("result")
        try:
            out = json.loads(res) if isinstance(res, str) else res
        except json.JSONDecodeError as exc:
            raise BadOutput(f"result text was not JSON: {exc}") from exc
    if not isinstance(out, dict):
        raise BadOutput("structured output was not an object")
    return {"output": out, "cost_usd": payload.get("total_cost_usd"), "usage": payload.get("usage") or {}}


class ClaudeRunner:
    """Real runner. `plan()` is a structured call; `stream_answer()` yields text deltas then a final result."""

    def __init__(self, planner_model=None, answer_model=None, timeout=120.0, sleep=time.sleep):
        self.planner_model = planner_model or MODEL_PLANNER
        self.answer_model = answer_model or MODEL_ANSWER
        self.timeout = timeout
        self._sleep = sleep
        self.cost_usd = 0.0  # running total for the question, read by the agent for the done event

    def _spawn(self, argv, prompt, cwd):
        if len(prompt.encode("utf-8")) > MAX_STDIN_BYTES:
            raise ValueError("prompt over the stdin cap")
        return subprocess.Popen(
            argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", start_new_session=(os.name != "nt"),
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
        )

    def plan(self, prompt: str, system: str, schema: dict) -> dict:
        argv = _argv(self.planner_model, system, ["--output-format", "json", "--json-schema", json.dumps(schema)])
        bad = timeouts = rate = 0
        while True:
            with tempfile.TemporaryDirectory(prefix="stewards_claude_") as cwd:
                proc = self._spawn(argv, prompt, cwd)
                try:
                    out, err = proc.communicate(input=prompt, timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    timeouts += 1
                    if timeouts <= 1:
                        continue
                    raise ClaudeTimeout(f"claude exceeded {self.timeout}s twice") from None
            try:
                if proc.returncode != 0:
                    raise classify(f"{out}\n{err}", proc.returncode)
                res = parse_json_result(out)
                self.cost_usd += float(res["cost_usd"] or 0)
                return res["output"]
            except BadOutput:
                bad += 1
                if bad <= 1:  # bad JSON is retried once
                    continue
                raise
            except RateLimited:
                rate += 1
                if rate > 2:
                    raise
                self._sleep(2 ** rate)

    def stream_answer(self, prompt: str, system: str) -> Iterator[tuple[str, Any]]:
        """Yields ("delta", text) for every text delta, then ("result", {"text", "cost_usd"}). Not retried once
        tokens have been delivered (the client has already seen them); a rate limit before the first token is."""
        argv = _argv(self.answer_model, system, ["--output-format", "stream-json", "--verbose", "--include-partial-messages"])
        for attempt in (1, 2, 3):
            started = False
            with tempfile.TemporaryDirectory(prefix="stewards_claude_") as cwd:
                proc = self._spawn(argv, prompt, cwd)
                timer = threading.Timer(self.timeout * 2, proc.kill)  # watchdog: a streamed answer takes longer than a plan
                timer.start()
                err_holder: list[str] = []
                threading.Thread(target=lambda: err_holder.append(proc.stderr.read()), daemon=True).start()
                try:
                    proc.stdin.write(prompt)
                    proc.stdin.close()
                    final = None
                    for line in proc.stdout:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            ev = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if ev.get("type") == "stream_event":
                            d = (ev.get("event") or {})
                            delta = d.get("delta") or {}
                            if d.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                                started = True
                                yield "delta", delta.get("text", "")
                        elif ev.get("type") == "result":
                            final = ev
                    proc.wait()
                finally:
                    timer.cancel()
                    if proc.poll() is None:
                        proc.kill()
            if final is None:
                err = classify(f"{''.join(err_holder)}", proc.returncode or 1)
                if isinstance(err, RateLimited) and not started and attempt < 3:
                    self._sleep(2 ** attempt)
                    continue
                if type(err) is ClaudeError and not "".join(err_holder).strip():
                    err = ClaudeTimeout("claude produced no result (killed by the watchdog or crashed)")
                raise err
            if final.get("is_error"):
                raise classify(f"{final.get('result', '')}")
            self.cost_usd += float(final.get("total_cost_usd") or 0)
            yield "result", {"text": final.get("result", ""), "cost_usd": final.get("total_cost_usd")}
            return


class FakeRunner:
    """Scripted runner for tests: `plans` is a list of dicts (or Exceptions) returned in order; `answer` is the
    text streamed in word-sized deltas. Records every prompt."""

    def __init__(self, plans=None, answer="", cost_usd=0.0):
        self.plans = list(plans or [])
        self.answer = answer
        self.plan_prompts: list[str] = []
        self.answer_prompts: list[str] = []
        self.cost_usd = cost_usd

    def plan(self, prompt, system, schema):
        self.plan_prompts.append(prompt)
        item = self.plans.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def stream_answer(self, prompt, system):
        self.answer_prompts.append(prompt)
        words = self.answer.split(" ")
        for i, w in enumerate(words):
            yield "delta", (w if i == 0 else " " + w)
        yield "result", {"text": self.answer, "cost_usd": self.cost_usd}


def make_planner_runnable(runner, system: str, schema: dict):
    """LangChain Runnable (prompt str -> plan dict) so LangGraph nodes can compose it (ORCHESTRATION contract)."""
    from langchain_core.runnables import RunnableLambda

    return RunnableLambda(lambda prompt: runner.plan(prompt, system, schema))
