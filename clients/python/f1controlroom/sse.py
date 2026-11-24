"""Server-Sent Events parsing (just what the API emits: id, event, data, comments)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, Optional


@dataclass
class Event:
    """One SSE frame. `data` is the decoded JSON object (or {"raw": text} when the payload is not JSON)."""

    event: str
    data: Dict[str, Any]
    id: Optional[int] = None


def parse_sse(lines: Iterable[str]) -> Iterator[Event]:
    ev, eid, data = "message", None, []
    for line in lines:
        if line == "":  # a blank line ends the frame
            if data:
                yield _build(ev, eid, "\n".join(data))
            ev, eid, data = "message", None, []
        elif line.startswith(":"):
            continue  # comment / keep-alive
        else:
            field, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if field == "event":
                ev = value
            elif field == "id":
                eid = int(value) if value.lstrip("-").isdigit() else None
            elif field == "data":
                data.append(value)
    if data:  # stream closed without a trailing blank line
        yield _build(ev, eid, "\n".join(data))


def _build(ev: str, eid: Optional[int], text: str) -> Event:
    try:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            payload = {"value": payload}
    except ValueError:
        payload = {"raw": text}
    return Event(event=ev, data=payload, id=eid)
