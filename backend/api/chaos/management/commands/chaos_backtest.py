"""Leave-one-season-out backtest for Chaos Point.

  python manage.py chaos_backtest --seasons 2018-2025 --models beta_binomial,lightgbm,kumo [--backfill-kumo]

Needs labels and features first: build_labels for every race, then build_features (see docs/v2/progress/A2-chaos.md).
--backfill-kumo also runs the production run_kumo (expanding window: context = earlier races only) for every race, which
stores the RAW per-race predictions that calibrate_and_store fits isotonic calibration on.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from api.chaos import backtest as BT
from api.chaos import history as H


class Command(BaseCommand):
    help = "Leave-one-season-out backtest (Beta-Binomial, LightGBM, Kumo) with Brier, log-loss, AUC, reliability, ECE."

    def add_arguments(self, p):
        p.add_argument("--seasons", default="", help="e.g. 2018-2025 or 2022,2023 (default: every stored season)")
        p.add_argument("--models", default="beta_binomial,lightgbm,kumo")
        p.add_argument("--out", default="", help="report directory (default: <CHAOS_FEATURES_DIR>/backtest)")
        p.add_argument("--backfill-kumo", action="store_true", help="also store raw Kumo predictions for every race")
        p.add_argument("--no-save", action="store_true", help="skip the ModelRun row")

    def handle(self, *a, **o):
        from api.chaos.tasks import features_dir

        seasons = None
        if o["seasons"]:
            if "-" in o["seasons"]:
                lo, hi = (int(x) for x in o["seasons"].split("-"))
                seasons = list(range(lo, hi + 1))
            else:
                seasons = [int(x) for x in o["seasons"].split(",")]
        names = [n.strip() for n in o["models"].split(",") if n.strip()]
        registry, skipped = BT.default_registry(names)
        races = H.load_races()
        try:
            report = BT.run_backtest(races, registry, skipped, seasons)
        except ValueError as e:
            raise CommandError(str(e)) from e
        paths = BT.write_report(report, o["out"] or features_dir() / "backtest")
        if not o["no_save"]:
            report["model_run"] = BT.save_run(report)
        for n, why in report["skipped_models"].items():
            self.stdout.write(f"SKIPPED {n}: {why}")
        self.stdout.write(f"prior strength per held-out season: {json.dumps(report['prior_strength'])}")
        for n in report["models"]:
            cells = report["results"][n]
            if cells:
                mean = lambda k: sum(c["overall"][k] for c in cells.values()) / len(cells)  # noqa: E731
                self.stdout.write(f"{n}: mean Brier {mean('brier'):.4f}  log-loss {mean('log_loss'):.4f}  ECE {mean('ece'):.4f}  ({len(cells)} cells)")
        self.stdout.write(report["canada_check"]["line"])
        self.stdout.write(f"report: {paths['json']} and {paths['csv']}")
        if o["backfill_kumo"]:
            if "kumo" not in registry:
                self.stdout.write("SKIPPED --backfill-kumo: kumo unavailable")
            else:
                from api.chaos import ml_tasks

                done = 0
                for r in races:
                    if seasons and r["year"] not in seasons:
                        continue
                    done += ml_tasks.run_kumo(r["year"], r["round"])["status"] == "ok"
                self.stdout.write(f"stored raw Kumo predictions for {done} races; calibrate_and_store will now fit isotonic")
