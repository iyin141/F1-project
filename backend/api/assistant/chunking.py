"""Section-aware chunking of parsed PDF pages. Pure Python, no I/O, no model, so it is cheap to test.

Why not a token-window splitter: a rule cited as "Article B5.10.1" must stay attached to its text, so the
chunker reads the FIA numbering and packs whole paragraphs, never cutting across a top-level article.

Token counts are an estimate (words x 1.3), not a tokenizer: the reference RAG pipeline lost a day to
tiktoken downloading its vocabulary at run time, and bge-small has a 512-token window, so a conservative
450 ceiling absorbs the estimation error without any download.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

MIN_TOKENS = 300
MAX_TOKENS = 450
_WORD_TO_TOKEN = 1.3

# "B5.10.1 text", "33.4 text" (older years: no letter prefix). The number needs at least one dot, so
# "12 laps" or "2026 Formula 1" are not article numbers.
_NUM_LINE = re.compile(r"^(?P<num>(?:[A-Z]{1,2})?\d{1,2}(?:\.\d{1,3})+)\s+(?P<rest>[A-Za-z(\"'].*)$")
# "ARTICLE B9: PERSONNEL LIMITATIONS", "APPENDIX B2: PARC FERME", "ARTICLE 33: PENALTIES" (upper case only: a wrapped line that starts "Article B3.5 until..." is a cross-reference)
_ARTICLE_LINE = re.compile(r"^(?P<kind>ARTICLE|APPENDIX)\s+(?P<num>[A-Z]{0,2}\d{1,2})\s*[:\-.]?\s*(?P<title>.*)$")
# Pre-2026 article headings: "52) ROLLING START" (upper-case title, number followed by a parenthesis).
_PAREN_ARTICLE = re.compile(r"^(?P<num>\d{1,2})\)\s+(?P<title>[A-Z][A-Z0-9 &'/,\-]{2,80})$")
_TOC_LINE = re.compile(r"^(?:ARTICLE|APPENDIX|[A-Z]{0,2}\d{1,2}(?:\.\d{1,3})*)\b.*\s\d{1,3}$")


@dataclass
class Chunk:
    text: str
    page: int
    section: str
    article: str
    tokens: int


def estimate_tokens(text: str) -> int:
    return int(len(text.split()) * _WORD_TO_TOKEN) + 1


def _norm_line(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip())


def clean_pages(pages: list[tuple[int, str]]) -> list[tuple[int, list[str]]]:
    """Normalise whitespace, drop running headers/footers and table-of-contents pages.

    Headers are found statistically: a line (digits ignored) present on >= 40 % of pages of a document of
    5+ pages is boilerplate. Short documents (a one-page stewards' decision) are left untouched.
    """
    split = [(n, [re.sub(r"[ \t ]+", " ", ln).strip() for ln in t.splitlines()]) for n, t in pages]
    split = [(n, [ln for ln in lines if ln]) for n, lines in split]
    if len(split) >= 5:
        freq = Counter(_norm_line(ln) for _, lines in split for ln in set(_norm_line(x) for x in lines if len(x) <= 80))
        boiler = {k for k, c in freq.items() if c >= 0.4 * len(split)}  # only short lines: body text is never boilerplate
        split = [(n, [ln for ln in lines if _norm_line(ln) not in boiler]) for n, lines in split]
    out = []
    for n, lines in split:
        if sum(1 for ln in lines if _TOC_LINE.match(ln)) >= 8:  # contents page: titles and page numbers only
            continue
        out.append((n, lines))
    return out


@dataclass
class _Unit:
    text: str
    page: int
    section: str
    article: str
    top: str
    new_section: bool


def _top(num: str) -> str:
    return num.split(".")[0]


def _units(pages: list[tuple[int, list[str]]]) -> list[_Unit]:
    units: list[_Unit] = []
    section, top, cur = "", "", None

    def close():
        nonlocal cur
        if cur and cur["lines"]:
            units.append(_Unit(" ".join(cur["lines"]), cur["page"], cur["section"], cur["article"], cur["top"], cur["new"]))
        cur = None

    for page, lines in pages:
        for ln in lines:
            m_art = _ARTICLE_LINE.match(ln) or _PAREN_ARTICLE.match(ln)
            m_num = _NUM_LINE.match(ln)
            if m_art and len(ln) < 100:
                close()
                top = m_art["num"]
                section = ln.strip()
                cur = {"lines": [ln], "page": page, "section": section, "article": top, "top": top, "new": True}
                continue
            if m_num:
                num, rest = m_num["num"], m_num["rest"]
                close()
                is_heading = num.count(".") == 1 and len(ln) <= 80 and not ln.rstrip().endswith((".", ",", ";", ":"))
                if _top(num) != top:
                    top = _top(num)
                    section = f"Article {top}"  # never keep the previous article's sub-heading (stale section bug)
                if is_heading:
                    section = ln
                cur = {"lines": [ln], "page": page, "section": section, "article": num, "top": _top(num), "new": is_heading}
                continue
            if cur is None:
                cur = {"lines": [], "page": page, "section": section, "article": "", "top": top, "new": False}
            cur["lines"].append(ln)
    close()
    return units


def _split_long(text: str, max_tokens: int) -> list[str]:
    """A single paragraph over the ceiling: cut at sentence ends, then at words as a last resort."""
    parts, cur = [], []
    for sent in re.split(r"(?<=[.;:])\s+", text):
        words = sent.split()
        while len(words) * _WORD_TO_TOKEN > max_tokens:  # a sentence longer than the ceiling
            if cur:
                parts.append(" ".join(cur))
                cur = []
            k = int(max_tokens / _WORD_TO_TOKEN)
            parts.append(" ".join(words[:k]))
            words = words[k:]
        sent = " ".join(words)
        if cur and estimate_tokens(" ".join(cur + [sent])) > max_tokens:
            parts.append(" ".join(cur))
            cur = []
        if sent:
            cur.append(sent)
    if cur:
        parts.append(" ".join(cur))
    return parts


def chunk_pages(pages: list[tuple[int, str]], min_tokens: int = MIN_TOKENS, max_tokens: int = MAX_TOKENS) -> list[Chunk]:
    """pages: [(page_number, text)] -> chunks of about min..max tokens, each tagged with page, section, article.

    Packing: whole paragraphs, in order. A chunk is closed when (a) the next paragraph would push it over
    max_tokens, (b) the next paragraph belongs to a different top-level article (never mix Article B5 and B6,
    even if that leaves a small chunk), or (c) it already has min_tokens and a new numbered sub-heading starts.
    """
    out: list[Chunk] = []
    cur: list[_Unit] = []

    def flush():
        nonlocal cur
        if cur:
            text = "\n".join(u.text for u in cur)
            out.append(Chunk(text, cur[0].page, cur[0].section, cur[0].article, estimate_tokens(text)))
        cur = []

    for u in _units(clean_pages(pages)):
        pieces = [u.text] if estimate_tokens(u.text) <= max_tokens else _split_long(u.text, max_tokens)
        for i, piece in enumerate(pieces):
            unit = u if len(pieces) == 1 else _Unit(piece, u.page, u.section, u.article, u.top, u.new_section and i == 0)
            size = sum(estimate_tokens(x.text) for x in cur)
            if cur and (
                cur[0].top != unit.top
                or size + estimate_tokens(unit.text) > max_tokens
                or (unit.new_section and size >= min_tokens)
            ):
                flush()
            cur.append(unit)
    flush()
    return out


def embedding_input(chunk: Chunk) -> str:
    """What gets embedded: the section title gives the passage its context (the stored text stays clean)."""
    head = chunk.section if chunk.section and not chunk.text.startswith(chunk.section) else ""
    return f"{head}\n{chunk.text}".strip()
