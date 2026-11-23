"""Optional start_m / end_m / channels / format params for the existing telemetry endpoints.

With none of them given, `TelemetryOptions.is_default` is True and the callers take their
original code path untouched (golden snapshots in tests/ prove the bytes are identical).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

CHANNELS = ("speed", "throttle", "brake", "gear", "rpm", "drs", "time")
# channel -> (key in the response row, key in the stored lap payload)
_MAP = {
    "speed": ("speed_kph", "speed"),
    "throttle": ("throttle_pct", "throttle"),
    "brake": ("brake", "brake"),
    "gear": ("gear", "gear"),
    "rpm": ("rpm", "rpm"),
    "drs": ("drs", "drs"),
    "time": ("time_seconds", "elapsed_s"),
}
DEFAULT_KEYS = ("lap_number", "sector", "time_seconds", "distance_m", "speed_kph", "throttle_pct", "brake", "rpm", "gear")
DRS_OPEN_MIN = 10  # FastF1 DRS channel: >= 10 means the flap is open
TIME_KEY = "elapsed_s"  # stored seconds-from-lap-start array; never part of a default response


def _num(query, name):
    raw = query.get(name)
    if raw is None or raw == "":
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number (metres)") from None
    if not math.isfinite(v) or v < 0:
        raise ValueError(f"{name} must be a non-negative number (metres)")
    return v


@dataclass(frozen=True)
class TelemetryOptions:
    start_m: float | None = None
    end_m: float | None = None
    channels: tuple | None = None
    columnar: bool = False

    @property
    def is_default(self) -> bool:
        return self.start_m is None and self.end_m is None and self.channels is None and not self.columnar

    def cache_suffix(self) -> str:
        if self.is_default:
            return ""
        return f":SM{self.start_m}:EM{self.end_m}:C{','.join(self.channels or ())}:F{'col' if self.columnar else 'row'}"

    def filters(self) -> dict:
        return {
            "start_m": self.start_m, "end_m": self.end_m,
            "channels": list(self.channels) if self.channels else None,
            "format": "columnar" if self.columnar else "rows",
        }

    # -- applying -------------------------------------------------------------

    def slice(self, lap: dict) -> dict:
        """Keep only samples with start_m <= distance <= end_m (every per-sample array)."""
        if self.start_m is None and self.end_m is None:
            return lap
        dist = lap.get("distance") or []
        lo = -math.inf if self.start_m is None else self.start_m
        hi = math.inf if self.end_m is None else self.end_m
        keep = [i for i, d in enumerate(dist) if d is not None and lo <= d <= hi]
        n = len(dist)
        return {k: ([v[i] for i in keep] if isinstance(v, list) and len(v) == n else v) for k, v in lap.items()}

    def rows(self, lap: dict, lap_number: int | None) -> list[dict]:
        """Row dicts for one stored lap after slicing and channel selection."""
        from api.services.extraction import extract_telemetry

        lap = self.slice(lap)
        if self.channels is None:
            return extract_telemetry(lap, lap_number=lap_number)
        dist = lap.get("distance") or []
        out = []
        for i, d in enumerate(dist):
            row = {"lap_number": lap_number, "distance_m": d}
            for ch in self.channels:
                key, src = _MAP[ch]
                arr = lap.get(src) or []
                v = arr[i] if i < len(arr) else None
                if ch == "brake":
                    v = bool(v)
                elif ch == "drs":
                    v = None if v is None else bool(v >= DRS_OPEN_MIN)
                row[key] = v
            out.append(row)
        return out

    def empty_keys(self) -> list[str]:
        """Row keys, for a columnar response that has no rows."""
        if self.channels is None:
            return list(DEFAULT_KEYS)
        return ["lap_number", "distance_m", *(_MAP[c][0] for c in self.channels)]

    def finish(self, rows: list[dict], extra_keys=()):
        """Rows as-is, or {key: [values]} when format=columnar (extra_keys name per-row fields
        added after extraction, e.g. driver_code, so an empty result keeps the same keys)."""
        if not self.columnar:
            return rows
        keys = list(rows[0]) if rows else self.empty_keys() + list(extra_keys)
        return {k: [r.get(k) for r in rows] for k in keys}

    def apply_to_rows(self, rows: list[dict]) -> list[dict]:
        """Slice + channel-select rows that already exist (a live task result, default row shape)."""
        lo = -math.inf if self.start_m is None else self.start_m
        hi = math.inf if self.end_m is None else self.end_m
        rows = [r for r in rows if r.get("distance_m") is not None and lo <= r["distance_m"] <= hi]
        if self.channels is None:
            return rows
        out = []
        for r in rows:
            row = {k: r[k] for k in ("driver_code", "lap_number", "distance_m") if k in r}
            for ch in self.channels:
                key = _MAP[ch][0]
                row[key] = r.get(key)  # drs / time are None unless the live rows carried them
            out.append(row)
        return out

    def apply_to_payload(self, payload: dict) -> dict:
        """Apply the params to a finished default-shape telemetry or overlay payload."""
        if isinstance(payload.get("data"), list):
            rows = self.apply_to_rows(payload["data"])
            payload["data"] = self.finish(rows, ("driver_code",))
            count = len(rows)
        elif isinstance(payload.get("traces"), list):
            count = 0
            for t in payload["traces"]:
                rows = self.apply_to_rows(t.get("data") or [])
                count += len(rows)
                t["data"] = self.finish(rows, ("driver_code",))
        else:
            return payload
        if isinstance(payload.get("meta"), dict):
            payload["meta"]["row_count"] = count
        if isinstance(payload.get("filters_applied"), dict):
            payload["filters_applied"].update(self.filters())
        return payload


def parse_options(query) -> TelemetryOptions:
    """Read the four optional params from request.query_params; ValueError -> HTTP 400 in the views."""
    start, end = _num(query, "start_m"), _num(query, "end_m")
    if start is not None and end is not None and start >= end:
        raise ValueError("start_m must be less than end_m")
    channels = None
    raw = query.get("channels")
    if raw is not None:
        parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
        bad = [p for p in parts if p not in CHANNELS]
        if not parts or bad:
            raise ValueError("channels must be a comma-separated subset of: " + ", ".join(CHANNELS)
                             + (f" (unknown: {', '.join(bad)})" if bad else ""))
        channels = tuple(dict.fromkeys(parts))
    fmt = (query.get("format") or "rows").lower()
    if fmt not in ("rows", "columnar"):
        raise ValueError("format must be 'rows' or 'columnar'")
    return TelemetryOptions(start, end, channels, fmt == "columnar")


class _SettingsWithoutFormatOverride:
    """DRF settings proxy with URL_FORMAT_OVERRIDE off."""

    def __getattr__(self, name):
        from rest_framework.settings import api_settings

        return None if name == "URL_FORMAT_OVERRIDE" else getattr(api_settings, name)


def _negotiation_class():
    from rest_framework.negotiation import DefaultContentNegotiation

    class NoFormatOverrideNegotiation(DefaultContentNegotiation):
        """DRF treats ?format=<x> as a renderer pick and 404s unknown values; on the telemetry
        views ?format= means rows|columnar instead (JSON is the only renderer anyway)."""

        settings = _SettingsWithoutFormatOverride()

    return NoFormatOverrideNegotiation


NoFormatOverrideNegotiation = _negotiation_class()


def apply_to_stream(response, options):
    """Wrap a streamed (DB-miss) JSON result so the requested params are applied to it.
    Non-streaming responses, default options and non-result chunks (timeout/error) pass through."""
    import json

    from django.http import StreamingHttpResponse

    if options.is_default or not isinstance(response, StreamingHttpResponse):
        return response

    def convert(buf: bytes) -> bytes:
        try:
            payload = json.loads(buf)
        except ValueError:
            return buf
        if not isinstance(payload, dict):
            return buf
        return json.dumps(options.apply_to_payload(payload)).encode()

    if response.is_async:
        async def gen():
            buf = b""
            async for part in response.streaming_content:
                buf += part
            yield convert(buf)
    else:
        def gen():
            yield convert(b"".join(response.streaming_content))

    new = StreamingHttpResponse(gen(), content_type=response.get("Content-Type", "application/json"))
    for h in ("Cache-Control", "X-Accel-Buffering"):
        if response.has_header(h):
            new[h] = response[h]
    return new
