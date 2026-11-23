"""Fetch a small, polite sample of the FIA corpus and register it.

  python manage.py fetch_corpus --regs 2026:B --decisions 4 [--ingest]

Rate-limited (robots.txt Crawl-delay, 10 s), robots-checked, generic User-Agent, sha256-deduped.
`--limit` is a hard cap on downloaded files. This is not a bulk downloader.
"""
from django.core.management.base import BaseCommand

from api.assistant import fetch
from api.assistant.ingest import ingest_source


class Command(BaseCommand):
    help = "Fetch FIA regulations / stewards' decision PDFs (polite, capped) and optionally ingest them."

    def add_arguments(self, p):
        p.add_argument("--regs", nargs="*", default=[], metavar="YEAR:SECTION",
                       help="latest issue of a regulation section, e.g. 2026:B (sporting) 2026:C (technical)")
        p.add_argument("--decisions", type=int, default=0, help="how many current-event decision/note PDFs to fetch")
        p.add_argument("--limit", type=int, default=10, help="hard cap on files downloaded in this run")
        p.add_argument("--ingest", action="store_true", help="ingest each stored file synchronously afterwards")

    def handle(self, *a, regs, decisions, limit, ingest, **kw):
        f = fetch.Fetcher()
        wanted = []
        if regs:
            cands = fetch.parse_regulations(f.get(fetch.REGS_LISTING).text)
            for spec in regs:
                year, sec = spec.split(":")
                hit = [c for c in cands if c.year == int(year) and f"section {sec.lower()}" in c.title.lower()]
                if not hit:
                    self.stderr.write(f"no regulation found for {spec}")
                wanted += hit[:1]
        if decisions:
            allc = fetch.parse_decisions(f.get(fetch.DECISIONS_LISTING).text)
            # mix: stewards' decisions first, then event notes, so the sample covers both types
            decs = [c for c in allc if c.doc_type == "stewards_decision"]
            notes = [c for c in allc if c.doc_type == "event_notes"]
            wanted += (decs[: max(decisions - 1, 1)] + notes[:1])[:decisions]
        stored = []
        downloads = 0
        for cand in wanted:
            if downloads >= limit:
                self.stdout.write("limit reached")
                break
            src, state = fetch.fetch_candidate(f, cand)
            downloads += state in ("stored", "duplicate_content")
            self.stdout.write(f"{state:17} {cand.doc_type:18} {cand.url.rsplit('/', 1)[-1]}")
            if src is not None:
                stored.append(src)
        if ingest:
            for src in stored:
                self.stdout.write(f"ingest {src.pk}: {ingest_source(src)}")
