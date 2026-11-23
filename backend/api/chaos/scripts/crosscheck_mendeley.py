"""Cross-check our SC/VSC labels against the Mendeley "Multi-Season F1 Lap Dataset with SC labels (2022-2025)"
(https://data.mendeley.com/datasets/djr8rnjtjp/1, CC BY 4.0). Plan 00 section D.

DEFERRED: needs the CSV download and a populated DB (build_labels run for 2022-2025). Column names of the dataset
were not inspected, so they are arguments with auto-detect from common spellings; pass them if detection fails.

  cd backend && DJANGO_SETTINGS_MODULE=f1_project.settings python -m api.chaos.scripts.crosscheck_mendeley \
      path/to/dataset.csv [--sc-col SafetyCar] [--kind sc|vsc|both] [--out report.json]

Compares per race on the set of laps flagged neutralised: dataset (any row on the lap flagged) vs our label
intervals [lap, end_lap] of type sc (or vsc, or both). Reports lap-level precision / recall / F1 and the races with
the worst agreement. Our end_lap is only as good as the stored data (see labels.neutral_events), so expect small
end-of-interval differences; a missing or extra whole deployment is the real signal.
"""
import argparse
import json

COLS = {
    "year": ["year", "season", "Year", "Season"],
    "round": ["round", "round_number", "Round", "RoundNumber"],
    "lap": ["lap", "lap_number", "LapNumber", "Lap"],
    "sc": ["safety_car", "SafetyCar", "sc", "SC", "is_safety_car", "safetycar", "SC_flag", "sc_label"],
}


def pick(df, given, key):
    if given:
        return given
    for c in COLS[key]:
        if c in df.columns:
            return c
    raise SystemExit(f"cannot find a {key} column in {list(df.columns)}; pass --{key}-col")


def dataset_laps(df, ycol, rcol, lcol, scol) -> dict:
    """{(year, round): set(laps flagged)} - a lap is flagged when any row on it is truthy."""
    flag = df[scol].astype(str).str.strip().str.lower().isin(["1", "1.0", "true", "yes", "sc", "y"])
    sub = df[flag]
    out = {k: set() for k in zip(df[ycol].astype(int), df[rcol].astype(int))}
    for y, r, lap in zip(sub[ycol].astype(int), sub[rcol].astype(int), sub[lcol].astype(int)):
        out[(y, r)].add(lap)
    return out


def our_laps(labels, kinds) -> set:
    """labels: iterable of (type, lap, end_lap)."""
    s = set()
    for t, lap, end in labels:
        if t in kinds and lap is not None:
            s |= set(range(lap, (end or lap) + 1))
    return s


def compare(theirs: dict, ours: dict) -> dict:
    """theirs/ours: {(year, round): set(laps)}. Only races present in both are scored."""
    tp = fp = fn = 0
    races = []
    for key in sorted(set(theirs) & set(ours)):
        a, b = ours[key], theirs[key]
        t, p, n = len(a & b), len(a - b), len(b - a)
        tp, fp, fn = tp + t, fp + p, fn + n
        races.append({"year": key[0], "round": key[1], "tp": t, "fp": p, "fn": n,
                      "agree": round(t / max(1, t + p + n), 3)})
    prec, rec = tp / max(1, tp + fp), tp / max(1, tp + fn)
    return {"races": len(races), "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(2 * prec * rec / max(1e-9, prec + rec), 4),
            "worst": sorted(races, key=lambda r: r["agree"])[:10], "per_race": races}


def main(argv=None):
    import django
    import pandas as pd

    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--year-col"), ap.add_argument("--round-col"), ap.add_argument("--lap-col"), ap.add_argument("--sc-col")
    ap.add_argument("--kind", choices=["sc", "vsc", "both"], default="sc")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    django.setup()
    from api.chaos.models import RaceEventLabel

    df = pd.read_csv(a.csv)
    y, r, lap, sc = (pick(df, a.year_col, "year"), pick(df, a.round_col, "round"), pick(df, a.lap_col, "lap"), pick(df, a.sc_col, "sc"))
    kinds = {"sc": {"sc"}, "vsc": {"vsc"}, "both": {"sc", "vsc"}}[a.kind]
    theirs = dataset_laps(df, y, r, lap, sc)
    ours = {}
    for key in theirs:
        rows = RaceEventLabel.objects.filter(year=key[0], round_number=key[1]).values_list("type", "lap", "end_lap")
        if rows:  # only races we have labelled
            ours[key] = our_laps(rows, kinds)
    rep = compare(theirs, ours)
    print(json.dumps({k: v for k, v in rep.items() if k != "per_race"}, indent=2))
    if a.out:
        open(a.out, "w").write(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
