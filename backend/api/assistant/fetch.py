"""Polite fetcher for the FIA corpus (regulations, stewards' decisions, event notes).

Sources (checked 2026-11-23):
* Regulations listing: https://www.fia.com/regulation/category/110 (F1 regulations, every issue as a PDF)
* Decision documents of the current event: https://www.fia.com/documents/championships/fia-formula-one-world-championship-14
robots.txt allows both (it disallows only /user/* paths) and sets `Crawl-delay: 10`; we honour that as the
default minimum gap between requests, check robots.txt before every host, and send a generic User-Agent.
No personal info is sent. Nothing here runs at import time or in tests (tests inject a fake `session`).
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import robotparser
from urllib.parse import unquote, urljoin, urlparse

from django.conf import settings

from .models import DocType, DocumentSource

BASE = "https://www.fia.com"
REGS_LISTING = f"{BASE}/regulation/category/110"
DECISIONS_LISTING = f"{BASE}/documents/championships/fia-formula-one-world-championship-14"
USER_AGENT = "F1ControlRoomCorpusFetcher/1.0 (small research corpus; polite, rate-limited)"
DEFAULT_DELAY = 10.0  # seconds, the robots.txt Crawl-delay
MAX_PDF_BYTES = 60 * 1024 * 1024
RANGE_CHUNK = 2 * 1024 * 1024


def data_dir() -> Path:
    """Where original PDFs live. Never in the repo by default (api/assistant/data is gitignored)."""
    d = os.environ.get("STEWARDS_DATA_DIR") or getattr(settings, "STEWARDS_DATA_DIR", None)
    p = Path(d) if d else Path(__file__).resolve().parent / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------- listing parsers (pure, tested on saved HTML snippets) ----------

_REG_RE = re.compile(
    r"fia_(?P<year>\d{4})_f1_regulations_-_section_(?P<sec>[a-f])_(?P<name>.+?)_-_iss_?(?P<iss>\d+)_-_(?P<date>\d{4}-\d{2}-\d{2})",
    re.I,
)
# 2022-2025: "fia_2025_formula_1_sporting_regulations_-_issue_5_-_2025-04-30.pdf",
# "formula_1_-_technical_regulations_-_2022_-_iss_11_-_2022-04-29.pdf", "2022_formula_1_sporting_regulations_-_iss_5_-_...".
# "_pu_" documents (2026 power unit regulations published early) are skipped.
_OLD_REG_RES = (
    re.compile(r"^(?:fia_)?(?P<year>\d{4})_formula_1_(?P<kind>sporting|technical)_regulations_-_iss(?:ue)?_?(?P<iss>\d+)_-_(?P<date>\d{4}-\d{2}-\d{2})", re.I),
    re.compile(r"^formula_1_-_(?P<kind>sporting|technical)_regulations_-_(?P<year>\d{4})_-_iss(?:ue)?_?(?P<iss>\d+)_-_(?P<date>\d{4}-\d{2}-\d{2})", re.I),
)
_HREF_RE = re.compile(r'href="([^"]+\.pdf)"', re.I)


@dataclass(frozen=True)
class Candidate:
    url: str
    doc_type: str
    year: int
    race: str = ""
    title: str = ""
    issue: int = 0  # regulation issue number, used to pick the latest


def pdf_links(html: str, base: str = BASE) -> list[str]:
    seen, out = set(), []
    for h in _HREF_RE.findall(html):
        u = urljoin(base, h.replace("&amp;", "&"))
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def parse_regulations(html: str) -> list[Candidate]:
    """All regulation PDFs on the listing, reduced to the latest issue per (year, section)."""
    best: dict[tuple[int, str], Candidate] = {}
    for u in pdf_links(html):
        path = unquote(urlparse(u).path)
        m = _REG_RE.search(path)
        if not m:
            old = next((mm for rx in _OLD_REG_RES if (mm := rx.match(path.rsplit("/", 1)[-1]))), None)
            if old:
                year, iss, kind = int(old["year"]), int(old["iss"]), old["kind"].lower()
                dt = DocType.SPORTING_REGS if kind == "sporting" else DocType.TECHNICAL_REGS
                cand = Candidate(u, dt.value, year, "", f"{year} F1 {kind.title()} Regulations (issue {iss}, {old['date']})", iss)
                key = (year, kind[0])
                if key not in best or iss > best[key].issue:
                    best[key] = cand
            continue
        year, sec, iss = int(m["year"]), m["sec"].lower(), int(m["iss"])
        dt = {"b": DocType.SPORTING_REGS, "c": DocType.TECHNICAL_REGS}.get(sec, DocType.OTHER_REGS)
        title = f"{year} F1 Regulations Section {sec.upper()} {m['name'].replace('_', ' ')} (issue {iss}, {m['date']})"
        cand = Candidate(u, dt.value, year, "", title, iss)
        key = (year, sec)
        if key not in best or iss > best[key].issue:
            best[key] = cand
    return sorted(best.values(), key=lambda c: (-c.year, c.title))


_EVENT_NOTE_WORDS = ("competition_notes", "race_director", "event_notes")
_DECISION_WORDS = ("infringement", "decision", "summons", "stewards")


def parse_decisions(html: str, include_summons: bool = True) -> list[Candidate]:
    """Decision documents (/system/files/decision-document/<year>_<event>_-_<subject>.pdf), typed by file name.
    Pure result sheets (classification, grid, entry list, scrutineering...) are skipped: not stewards material."""
    out = []
    for u in pdf_links(html):
        path = unquote(urlparse(u).path)
        if "/decision-document/" not in path:
            continue
        stem = path.rsplit("/", 1)[-1][:-4].lower()
        m = re.match(r"(\d{4})_(.+?)_-_(.+)$", stem)
        if not m:
            continue
        year, race, subject = int(m[1]), m[2].replace("_", " "), m[3]
        if any(w in subject for w in _EVENT_NOTE_WORDS):
            dt = DocType.EVENT_NOTES
        elif any(w in subject for w in _DECISION_WORDS):
            if not include_summons and "summons" in subject:
                continue
            dt = DocType.STEWARDS_DECISION
        else:
            continue
        out.append(Candidate(u, dt.value, year, race, f"{race} - {subject.replace('_', ' ')}"))
    return out


# ---------- polite HTTP ----------

class Fetcher:
    def __init__(self, session=None, delay: float | None = None, sleep=time.sleep, clock=time.monotonic):
        if session is None:
            import requests

            session = requests.Session()
        self.session = session
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.delay = float(os.environ.get("STEWARDS_FETCH_DELAY", DEFAULT_DELAY) if delay is None else delay)
        self._sleep, self._clock = sleep, clock
        self._last = None
        self._robots: dict[str, robotparser.RobotFileParser] = {}

    def _wait(self):
        if self._last is not None:
            gap = self.delay - (self._clock() - self._last)
            if gap > 0:
                self._sleep(gap)
        self._last = self._clock()

    def _allowed(self, url: str) -> bool:
        host = urlparse(url)
        root = f"{host.scheme}://{host.netloc}"
        if root not in self._robots:
            rp = robotparser.RobotFileParser()
            self._wait()
            r = self.session.get(f"{root}/robots.txt", timeout=30)
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
            else:  # no robots.txt: urllib semantics, everything allowed (a 401/403 means disallow all)
                rp.parse(["User-agent: *", "Disallow: /"] if r.status_code in (401, 403) else [])
            self._robots[root] = rp
        return self._robots[root].can_fetch(USER_AGENT, url)

    def get(self, url: str):
        if not self._allowed(url):
            raise PermissionError(f"robots.txt disallows {url}")
        last = None
        for attempt in range(3):  # transient network/TLS errors and truncated bodies: retry, each spaced by the delay
            self._wait()
            try:
                r = self.session.get(url, timeout=120)
                r.raise_for_status()
                want = r.headers.get("Content-Length") if hasattr(r, "headers") else None
                if want and want.isdigit() and len(r.content) != int(want):
                    raise OSError(f"short read {len(r.content)}/{want}")
                return r
            except Exception as exc:  # noqa: BLE001
                last = exc
        raise last

    def get_bytes(self, url: str, chunk: int = RANGE_CHUNK) -> bytes:
        """Download a file, in HTTP Range chunks when the server supports them. On this network a single long TLS
        stream of a multi-MB PDF dies with 'bad record MAC'; short ranged requests succeed and are retried
        one by one. Every request still waits the Crawl-delay. Falls back to one plain GET without Range support."""
        if not self._allowed(url):
            raise PermissionError(f"robots.txt disallows {url}")

        def ranged(lo, hi):
            last = None
            for _ in range(6):
                self._wait()
                try:
                    r = self.session.get(url, headers={"Range": f"bytes={lo}-{hi}"}, timeout=120)
                    r.raise_for_status()
                    return r
                except Exception as exc:  # noqa: BLE001
                    last = exc
            raise last

        first = ranged(0, chunk - 1)
        cr = first.headers.get("Content-Range") if hasattr(first, "headers") else None
        if first.status_code != 206 or not cr or "/" not in cr:
            return first.content if first.status_code == 200 else self.get(url).content
        total = int(cr.rsplit("/", 1)[1])
        parts = [first.content]
        have = len(parts[0])
        while have < total:
            if have > MAX_PDF_BYTES:
                raise ValueError(f"{url} larger than {MAX_PDF_BYTES} bytes")
            part = ranged(have, min(have + chunk, total) - 1).content
            if not part:
                raise OSError(f"empty range at {have}/{total}")
            parts.append(part)
            have += len(part)
        return b"".join(parts)


# ---------- storing ----------

def store_pdf(cand: Candidate, content: bytes, root: Path | None = None) -> tuple[DocumentSource, bool]:
    """Save the original PDF and register it. Idempotent: the same sha256 never makes a second row or file."""
    if not content.startswith(b"%PDF"):
        raise ValueError(f"not a PDF: {cand.url}")
    if b"%%EOF" not in content[-2048:]:  # a truncated download (seen with curl/schannel on Windows) is not stored
        raise ValueError(f"truncated PDF (no %%EOF): {cand.url}")
    sha = hashlib.sha256(content).hexdigest()
    existing = DocumentSource.objects.filter(sha256=sha).first()
    if existing:
        return existing, False
    root = root or data_dir()
    name = re.sub(r"[^A-Za-z0-9._-]", "_", unquote(urlparse(cand.url).path.rsplit("/", 1)[-1]))[:120]
    rel = f"{cand.doc_type}/{cand.year}/{sha[:12]}_{name}"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    src = DocumentSource.objects.create(
        url=cand.url, doc_type=cand.doc_type, year=cand.year, race=cand.race, title=cand.title[:300],
        sha256=sha, file_path=rel,
    )
    return src, True


def fetch_candidate(fetcher: Fetcher, cand: Candidate) -> tuple[DocumentSource | None, str]:
    """Download one candidate unless its URL is already registered (saves a request and the 10 s wait)."""
    known = DocumentSource.objects.filter(url=cand.url).first()
    if known:
        return known, "known"
    try:
        content = fetcher.get_bytes(cand.url)
    except ValueError:
        return None, "too_large"
    src, created = store_pdf(cand, content)
    return src, "stored" if created else "duplicate_content"


# ---------- season / event discovery ----------

def season_urls(html: str) -> dict[int, str]:
    """{year: season page URL} from the 'Season' drop-down on the decisions page."""
    out = {}
    for path, label in re.findall(r'<option[^>]*value="([^"]*/season/[^"]+)"[^>]*>\s*SEASON (\d{4})', html):
        out[int(label)] = urljoin(BASE, path)
    return out


def event_urls(html: str) -> list[str]:
    """Per-event page URLs listed in the season page's 'Event' drop-down (the season page itself shows only
    the latest event)."""
    paths = re.findall(r'<option[^>]*value="([^"]*/season/[^"]+/event/[^"]+)"', html)
    return [urljoin(BASE, p) for p in dict.fromkeys(paths)]


def season_candidates(fetcher: "Fetcher", season_url: str, include_summons: bool = False, log=lambda m: None) -> list[Candidate]:
    """All decision/event-note candidates of one season: season page -> one request per event page."""
    events = event_urls(fetcher.get(season_url).text)
    seen, out = set(), []
    for ev in events:
        # The event page lists every document on one page (probed: ?page=1.. repeats page 0), so one request.
        html = fetcher.get(ev).text
        for c in parse_decisions(html, include_summons):
            if c.url not in seen:
                seen.add(c.url)
                out.append(c)
        log(f"{time.strftime('%H:%M:%S')} {ev.rsplit('/', 1)[-1]}: {len(out)} candidates so far")
    return out
