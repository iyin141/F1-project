"""Hierarchical Beta-Binomial baseline. Race and lap-window scopes: circuit -> circuit type -> global.
Driver scope: driver -> team -> global. Posteriors come from history.Counts built over races strictly before the
target race. probability = posterior mean rate; p10/p90 = 10th/90th percentile of that rate's Beta posterior
(uncertainty about the rate, not about a single outcome)."""
from scipy.stats import beta as beta_dist

from . import history as H

MODEL = "beta_binomial"


def _row(scope, entity, target, stats):
    p, a, b, _ = stats
    # A very skewed Beta (a << 1) can put its mean outside its own 10-90 band, so the band is widened to contain
    # the reported mean: the contract is p10 <= probability <= p90.
    return dict(scope=scope, entity=entity, target=target, probability=p,
                p10=min(p, float(beta_dist.ppf(0.10, a, b))), p90=max(p, float(beta_dist.ppf(0.90, a, b))))


def predict(history, target, n_windows=None, drivers=None) -> list[dict]:
    """history: race dicts strictly before `target` (a race meta dict with circuit/ctype; drivers = {code: {team}}).
    Returns prediction rows (scope, entity, target, probability, p10, p90)."""
    counts = H.Counts()
    for r in history:
        counts.update(r)
    out = []
    for t in H.RACE_TARGETS:
        out.append(_row("race", "", t, counts.rate("race", t, H.race_chain(target))))
    for code, d in (drivers or {}).items():
        for t in H.DRIVER_TARGETS:
            out.append(_row("driver", code, t, counts.rate("drv", t, H.drv_chain(code, d["team"]))))
    for w in range(1, (n_windows or 0) + 1):
        for t in H.RACE_TARGETS:
            out.append(_row("lap_window", f"w{w}", t, counts.rate("win", t, H.win_chain(target, w))))
    return out
