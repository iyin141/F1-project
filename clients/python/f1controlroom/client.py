"""F1Client: a thin typed wrapper over the public GET endpoints, plus the assistant's SSE stream.

Why httpx (not requests): one dependency gives a sync client, response streaming for SSE, timeouts per phase, and a
built-in MockTransport, so the tests need no network and no extra mocking library.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Union

import httpx

from .errors import (
    AuthError, BadRequest, F1Error, NotFound, PendingError, PendingTimeout, RateLimited, ServerError,
    ServiceUnavailable,
)
from .sse import Event, parse_sse

JSON = Any
Listish = Union[str, Sequence[str]]
POLL_SECONDS = 2.0  # used when a 202 carries no Retry-After


@dataclass
class Answer:
    """What `ask_answer()` returns: the streamed text with its citations and the final `done` payload."""

    text: str = ""
    citations: List[Dict[str, Any]] = field(default_factory=list)
    done: Dict[str, Any] = field(default_factory=dict)
    task_key: Optional[str] = None


def _retry_after(resp: httpx.Response, body: Any) -> Optional[float]:
    raw = resp.headers.get("Retry-After")
    if raw is None and isinstance(body, dict):
        raw = body.get("retry_after")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None  # an HTTP-date form is not used by this API


def _body(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text


def _message(body: Any, status: int) -> str:
    if isinstance(body, dict):
        for key in ("detail", "error", "reason", "message"):
            if body.get(key):
                return f"HTTP {status}: {body[key]}"
    return f"HTTP {status}"


def raise_for_response(resp: httpx.Response) -> None:
    """Map an error response to one of our exceptions. 2xx returns normally (202 is handled by the caller)."""
    s = resp.status_code
    if s < 400:
        return
    body = _body(resp)
    msg = _message(body, s)
    if s == 400:
        raise BadRequest(msg, s, body)
    if s in (401, 403):
        raise AuthError(msg, s, body)
    if s == 404:
        raise NotFound(msg, s, body)
    if s == 429:
        raise RateLimited(msg, s, body, _retry_after(resp, body))
    if s == 503:
        raise ServiceUnavailable(msg, s, body, _retry_after(resp, body))
    if s >= 500:
        raise ServerError(msg, s, body)
    raise F1Error(msg, s, body)


def _param(value: Any) -> Any:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value)
    return value


class F1Client:
    """
    Args:
        api_key: sent as `X-API-Key`.
        base_url: the server root, with or without a trailing `/api`.
        wait: default for every call. None (default) raises `PendingError` on a 202. A number polls for that many
            seconds and raises `PendingTimeout` if the answer is still pending.
        retries: how many times to repeat a request that got 503 + Retry-After (waits Retry-After, capped by
            `max_retry_after`). 0 raises `ServiceUnavailable` at once.
        client / sleep: injection points for tests.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "http://localhost",
        *,
        timeout: float = 60.0,
        wait: Optional[float] = None,
        retries: int = 2,
        max_retry_after: float = 30.0,
        client: Optional[httpx.Client] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        root = base_url.rstrip("/")
        self.api_url = root if root.endswith("/api") else root + "/api"
        self.wait, self.retries, self.max_retry_after, self._sleep = wait, retries, max_retry_after, sleep
        self._headers = {"X-API-Key": api_key, "Accept": "application/json"}
        self._http = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "F1Client":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ core

    def get(self, path: str, *, wait: Optional[float] = None, **params: Any) -> JSON:
        """GET `/api/<path>`. None-valued params are dropped, lists are joined with commas."""
        wait = self.wait if wait is None else wait
        query = {k: _param(v) for k, v in params.items() if v is not None}
        url = f"{self.api_url}/{path.lstrip('/')}"
        deadline = None if not wait else time.monotonic() + wait
        retries_left = self.retries
        while True:
            resp = self._http.get(url, params=query, headers=self._headers)
            if resp.status_code == 202:
                body = _body(resp)
                ra = _retry_after(resp, body)
                task_key = body.get("task_key") if isinstance(body, dict) else None
                detail = body.get("detail", "pending") if isinstance(body, dict) else "pending"
                if deadline is None:
                    raise PendingError(f"pending: {detail}", body, task_key, ra)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PendingTimeout(f"still pending after {wait}s: {detail}", body, task_key, ra)
                self._sleep(min(ra if ra is not None else POLL_SECONDS, remaining))
                continue
            if resp.status_code == 503 and retries_left > 0:
                retries_left -= 1
                ra = _retry_after(resp, _body(resp))
                self._sleep(min(ra if ra is not None else 1.0, self.max_retry_after))
                continue
            raise_for_response(resp)
            return self._decode(resp)

    @staticmethod
    def _decode(resp: httpx.Response) -> JSON:
        # On a cache or DB miss the v1 views answer 200 text/event-stream with one `data:` frame holding the JSON.
        if resp.headers.get("content-type", "").startswith("text/event-stream"):
            for ev in parse_sse(resp.text.splitlines()):
                return ev.data
            raise F1Error("empty event stream", resp.status_code)
        return resp.json()

    # ------------------------------------------------------------------ v1: schedule, results, drivers

    def me(self) -> JSON:
        return self.get("auth/me/")

    def schedule(self, year: int) -> JSON:
        return self.get(f"races/{year}/")

    def race(self, year: int, round: int) -> JSON:
        return self.get(f"races/{year}/{round}/")

    def results(self, year: int, round: int) -> JSON:
        return self.get(f"races/{year}/{round}/results/")

    def qualifying(self, year: int, round: int) -> JSON:
        return self.get(f"races/{year}/{round}/qualifying/")

    def sprint(self, year: int, round: int) -> JSON:
        return self.get(f"races/{year}/{round}/sprint/")

    def sprint_shootout(self, year: int, round: int) -> JSON:
        return self.get(f"races/{year}/{round}/sprint-shootout/")

    def practice(self, year: int, round: int, session_name: str) -> JSON:
        return self.get(f"races/{year}/{round}/practice/{session_name}/")

    def driver_standings(self, year: int) -> JSON:
        return self.get(f"drivers/{year}/")

    def driver_season(self, code: str, year: int) -> JSON:
        return self.get(f"drivers/{code}/{year}/")

    def driver_career(self, code: str) -> JSON:
        return self.get(f"drivers/{code}/career/")

    def search_drivers(self, year: Optional[int] = None) -> JSON:
        return self.get("drivers/search/", year=year)

    def search_drivers_by_name(self, q: str, year: Optional[int] = None) -> JSON:
        return self.get("drivers/search-by-name/", q=q, year=year)

    def constructor_standings(self, year: int) -> JSON:
        return self.get(f"constructors/{year}/")

    # ------------------------------------------------------------------ v1: analysis

    def _analysis(self, name: str, year: int, round: int, **params: Any) -> JSON:
        return self.get(f"analysis/races/{year}/{round}/{name}/", **params)

    def laps(self, year: int, round: int, *, driver: Optional[str] = None, session: Optional[str] = None,
             limit: Optional[int] = None) -> JSON:
        return self._analysis("laps", year, round, driver=driver, session=session, limit=limit)

    def stints(self, year: int, round: int, *, driver: Optional[str] = None, session: Optional[str] = None,
               limit: Optional[int] = None) -> JSON:
        return self._analysis("stints", year, round, driver=driver, session=session, limit=limit)

    def pace(self, year: int, round: int, *, driver: Optional[str] = None, session: Optional[str] = None,
             limit: Optional[int] = None) -> JSON:
        return self._analysis("pace", year, round, driver=driver, session=session, limit=limit)

    def tyre_strategy(self, year: int, round: int, *, driver: Optional[str] = None, session: Optional[str] = None,
                      limit: Optional[int] = None) -> JSON:
        return self._analysis("tyre-strategy", year, round, driver=driver, session=session, limit=limit)

    def sector_analysis(self, year: int, round: int, *, driver: Optional[str] = None, session: Optional[str] = None,
                        limit: Optional[int] = None) -> JSON:
        return self._analysis("sector-analysis", year, round, driver=driver, session=session, limit=limit)

    def telemetry(self, year: int, round: int, *, driver: str, lap: Optional[int] = None,
                  session: Optional[str] = None, limit_points: Optional[int] = None, stride: Optional[int] = None,
                  sector_start: Optional[int] = None, sector_end: Optional[int] = None,
                  start_m: Optional[float] = None, end_m: Optional[float] = None,
                  channels: Optional[Listish] = None, format: Optional[str] = None) -> JSON:
        """`start_m`, `end_m`, `channels` and `format` ("rows" or "columnar") are the v2 optional parameters;
        leaving them out gives the v1 response unchanged."""
        return self._analysis("telemetry", year, round, driver=driver, lap=lap, session=session,
                              limit_points=limit_points, stride=stride, sector_start=sector_start,
                              sector_end=sector_end, start_m=start_m, end_m=end_m, channels=channels, format=format)

    def telemetry_overlay(self, year: int, round: int, *, driver_a: str, driver_b: str, lap_a: Optional[int] = None,
                          lap_b: Optional[int] = None, session: Optional[str] = None,
                          limit_points: Optional[int] = None, stride: Optional[int] = None,
                          sector_start: Optional[int] = None, sector_end: Optional[int] = None,
                          start_m: Optional[float] = None, end_m: Optional[float] = None,
                          channels: Optional[Listish] = None, format: Optional[str] = None) -> JSON:
        return self._analysis("telemetry/overlay", year, round, driver_a=driver_a, driver_b=driver_b, lap_a=lap_a,
                              lap_b=lap_b, session=session, limit_points=limit_points, stride=stride,
                              sector_start=sector_start, sector_end=sector_end, start_m=start_m, end_m=end_m,
                              channels=channels, format=format)

    def telemetry_summary(self, year: int, round: int, *, driver: Optional[str] = None, lap: Optional[int] = None,
                          session: Optional[str] = None, stride: Optional[int] = None) -> JSON:
        return self._analysis("telemetry/summary", year, round, driver=driver, lap=lap, session=session, stride=stride)

    # ------------------------------------------------------------------ v1: unified

    def _unified(self, name: str, year: int, round: int, **params: Any) -> JSON:
        return self.get(f"unified/races/{year}/{round}/{name}/", **params)

    def weather(self, year: int, round: int, *, session: Optional[str] = None, per_lap: Optional[bool] = None) -> JSON:
        return self._unified("weather", year, round, session=session, per_lap=per_lap)

    def pit_stops(self, year: int, round: int, *, session: Optional[str] = None, limit: Optional[int] = None) -> JSON:
        return self._unified("pit-stops", year, round, session=session, limit=limit)

    def incidents(self, year: int, round: int, *, session: Optional[str] = None, limit: Optional[int] = None,
                  radio: Optional[bool] = None) -> JSON:
        return self._unified("incidents", year, round, session=session, limit=limit, radio=radio)

    def positions(self, year: int, round: int, *, session: Optional[str] = None,
                  sample_interval: Optional[int] = None) -> JSON:
        return self._unified("positions", year, round, session=session, sample_interval=sample_interval)

    def drs(self, year: int, round: int, *, session: Optional[str] = None, driver: Optional[str] = None) -> JSON:
        return self._unified("drs", year, round, session=session, driver=driver)

    def track_status(self, year: int, round: int, *, session: Optional[str] = None) -> JSON:
        return self._unified("track-status", year, round, session=session)

    def full_session(self, year: int, round: int, *, session: Optional[str] = None, driver: Optional[str] = None,
                     include: Optional[Listish] = None) -> JSON:
        return self._unified("full-session", year, round, session=session, driver=driver, include=include)

    # ------------------------------------------------------------------ v2: track map

    def track_map(self, year: int, round: int, *, scheme: Optional[str] = None, wait: Optional[float] = None) -> JSON:
        """Polyline, corners, DRS zones and mini-sector boundaries. `scheme`: "distance" or "corners"."""
        return self._analysis("track-map", year, round, scheme=scheme, wait=wait)

    def mini_sectors(self, year: int, round: int, *, drivers: Listish, lap: Union[str, int] = "fastest",
                     scheme: Optional[str] = None, session: Optional[str] = None, wait: Optional[float] = None) -> JSON:
        return self._analysis("mini-sectors", year, round, drivers=drivers, lap=lap, scheme=scheme, session=session,
                              wait=wait)

    def telemetry_delta(self, year: int, round: int, *, ref: str, cmp: str, lap: Union[str, int] = "fastest",
                        session: Optional[str] = None, wait: Optional[float] = None) -> JSON:
        """Delta-time trace by distance; positive means `cmp` is slower than `ref`."""
        return self._analysis("telemetry/delta", year, round, ref=ref, cmp=cmp, lap=lap, session=session, wait=wait)

    # ------------------------------------------------------------------ v2: Chaos Point

    def chaos_race(self, year: int, round: int, *, model: Optional[str] = None, wait: Optional[float] = None) -> JSON:
        """`model`: auto (default), kumo_calibrated, kumo or baseline. 202 while predictions are being built."""
        return self.get(f"chaos/races/{year}/{round}/", model=model, wait=wait)

    def chaos_drivers(self, year: int, round: int, *, model: Optional[str] = None, wait: Optional[float] = None) -> JSON:
        return self.get(f"chaos/races/{year}/{round}/drivers/", model=model, wait=wait)

    def chaos_laps(self, year: int, round: int, *, target: Optional[str] = None, model: Optional[str] = None,
                   wait: Optional[float] = None) -> JSON:
        return self.get(f"chaos/races/{year}/{round}/laps/", target=target, model=model, wait=wait)

    def chaos_circuits(self) -> JSON:
        return self.get("chaos/circuits/")

    def chaos_circuits_summary(self) -> JSON:
        return self.get("chaos/circuits/summary/")

    def chaos_circuit_history(self, circuit: str) -> JSON:
        return self.get(f"chaos/circuits/{circuit}/history/")

    def chaos_driver_profile(self, code: str) -> JSON:
        return self.get(f"chaos/drivers/{code}/profile/")

    def chaos_model(self) -> JSON:
        """Latest model runs, calibration tables and the leave-one-season-out backtest (null until one has run)."""
        return self.get("chaos/model/")

    # ------------------------------------------------------------------ v2: Stewards assistant (SSE)

    def _stream(self, method: str, path: str, *, json: Any = None, last_event_id: Optional[int] = None) -> Iterator[Event]:
        headers = {**self._headers, "Accept": "text/event-stream"}
        if last_event_id is not None:
            headers["Last-Event-ID"] = str(last_event_id)
        timeout = httpx.Timeout(self._http.timeout.connect, read=None)  # tokens can be many seconds apart
        with self._http.stream(method, f"{self.api_url}/{path}", json=json, headers=headers, timeout=timeout) as resp:
            if resp.status_code != 200:
                resp.read()
                raise_for_response(resp)
                raise F1Error(f"unexpected HTTP {resp.status_code}", resp.status_code)
            yield from parse_sse(resp.iter_lines())

    def ask_events(self, task_key: str, last_event_id: Optional[int] = None) -> Iterator[Event]:
        """Replay and follow an earlier question. With `last_event_id` the stream continues after that event."""
        return self._stream("GET", f"assistant/ask/{task_key}/events", last_event_id=last_event_id)

    def ask(self, question: str, *, year: Optional[int] = None, round: Optional[int] = None,
            max_reconnects: int = 2) -> Iterator[Event]:
        """Ask the stewards and rules assistant; yields `Event`s: status, token, citations, then done or error.

        If the connection drops before done/error, the stream is resumed from the last event id through
        `ask_events` (up to `max_reconnects` times) so no token is lost or repeated. An `error` event is yielded,
        not raised: check `event.event == "error"` and `event.data["code"]`.
        """
        body: Dict[str, Any] = {"question": question}
        if year is not None:
            body["year"] = year
        if round is not None:
            body["round"] = round
        task_key: Optional[str] = None
        last_id: Optional[int] = None
        reconnects = 0
        while True:
            if task_key is None:
                source = self._stream("POST", "assistant/ask", json=body)
            else:
                source = self.ask_events(task_key, last_id)
            try:
                for ev in source:
                    if ev.id is not None:
                        last_id = ev.id
                    task_key = task_key or ev.data.get("task_key")
                    yield ev
                    if ev.event in ("done", "error"):
                        return
            except httpx.TransportError as exc:
                if task_key is None or reconnects >= max_reconnects:
                    raise F1Error(f"stream interrupted: {exc}") from exc
            else:
                if task_key is None or reconnects >= max_reconnects:
                    return  # the server closed the stream without a terminal event
            reconnects += 1

    def ask_answer(self, question: str, *, year: Optional[int] = None, round: Optional[int] = None) -> Answer:
        """Collect a whole answer. Raises F1Error if the stream ends with an `error` event."""
        out = Answer()
        for ev in self.ask(question, year=year, round=round):
            out.task_key = out.task_key or ev.data.get("task_key")
            if ev.event == "token":
                out.text += ev.data.get("text", "")
            elif ev.event == "citations":
                out.citations = ev.data.get("citations", [])
            elif ev.event == "done":
                out.done = ev.data
            elif ev.event == "error":
                raise F1Error(f"{ev.data.get('code')}: {ev.data.get('message')}", body=ev.data)
        return out
