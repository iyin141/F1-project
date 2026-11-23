"""Fetch the FIA corpus politely (rate-limited, robots-checked, sha256-deduped, resumable) and optionally ingest.

  python manage.py fetch_corpus --regs 2026:B                  # one latest-issue section
  python manage.py fetch_corpus --reg-years 2022 2023 2024 2025 2026   # Sporting + Technical, latest issue per year
  python manage.py fetch_corpus --seasons 2025 2026 --ingest   # stewards' decisions + event notes, every event
  python manage.py fetch_corpus --decisions 4                  # a handful from the current event (smoke test)

Already-registered URLs are skipped without a request, so an interrupted run resumes. `--limit` caps downloads.
"""
from django.core.management.base import BaseCommand

from api.assistant import fetch
from api.assistant.ingest import ingest_source


class Command(BaseCommand):
    help = "Fetch FIA regulations / stewards' decision PDFs (polite) and optionally ingest them."

    def add_arguments(self, p):
        p.add_argument("--regs", nargs="*", default=[], metavar="YEAR:SECTION")
        p.add_argument("--reg-years", nargs="*", type=int, default=[], help="Sporting + Technical regs of these years")
        p.add_argument("--decisions", type=int, default=0, help="a handful from the current event")
        p.add_argument("--seasons", nargs="*", type=int, default=[], help="every event of these seasons")
        p.add_argument("--include-summons", action="store_true")
        p.add_argument("--limit", type=int, default=10, help="hard cap on files downloaded in this run")
        p.add_argument("--ingest", action="store_true", help="ingest each stored file synchronously afterwards")

    def handle(self, *a, regs, reg_years, decisions, seasons, include_summons, limit, ingest, **kw):
        f = fetch.Fetcher()
        wanted = []
        if regs or reg_years:
            cands = fetch.parse_regulations(f.get(fetch.REGS_LISTING).text)
            for spec in regs:
                year, sec = spec.split(":")
                hit = [c for c in cands if c.year == int(year) and f"section {sec.lower()}" in c.title.lower()]
                if not hit:
                    self.stderr.write(f"no regulation found for {spec}")
                wanted += hit[:1]
            for y in reg_years:
                hit = [c for c in cands if c.year == y and c.doc_type in ("sporting_regs", "technical_regs")]
                wanted += hit
                self.stdout.write(f"{y}: {[c.title for c in hit]}")
        if decisions:
            allc = fetch.parse_decisions(f.get(fetch.DECISIONS_LISTING).text)
            decs = [c for c in allc if c.doc_type == "stewards_decision"]
            notes = [c for c in allc if c.doc_type == "event_notes"]
            wanted += (decs[: max(decisions - 1, 1)] + notes[:1])[:decisions]
        if seasons:
            urls = fetch.season_urls(f.get(fetch.DECISIONS_LISTING).text)
            for y in seasons:
                if y not in urls:
                    self.stderr.write(f"no season page for {y}")
                    continue
                found = fetch.season_candidates(f, urls[y], include_summons, log=self.stdout.write)
                self.stdout.write(f"season {y}: {len(found)} documents listed")
                wanted += found
        downloads = 0
        for cand in wanted:
            if downloads >= limit:
                self.stdout.write("limit reached")
                break
            try:
                src, state = fetch.fetch_candidate(f, cand)
            except Exception as exc:  # noqa: BLE001  one bad file must not stop a long polite run
                self.stderr.write(f"FAILED {cand.url}: {type(exc).__name__} {exc}")
                continue
            downloads += state in ("stored", "duplicate_content")
            self.stdout.write(f"{state:17} {cand.doc_type:18} {cand.url.rsplit('/', 1)[-1]}")
            if ingest and src is not None and src.ingested_at is None:
                try:
                    self.stdout.write(f"  ingest {src.pk}: {ingest_source(src)}")
                except Exception as exc:  # noqa: BLE001
                    self.stderr.write(f"  INGEST FAILED {src.pk}: {type(exc).__name__} {exc}")
