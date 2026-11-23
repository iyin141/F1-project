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
        m = _REG_RE.search(unquote(urlparse(u).path))
        if not m:
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


def parse_decisions(html: str) -> list[Candidate]:
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
    r = fetcher.get(cand.url)
    if len(r.content) > MAX_PDF_BYTES:
        return None, "too_large"
    src, created = store_pdf(cand, r.content)
    return src, "stored" if created else "duplicate_content"
