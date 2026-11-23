"""Binary-forecast metrics (numpy only). p = predicted probability, y = 0/1 outcome."""
import numpy as np

EPS = 1e-15


def brier(p, y) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def log_loss(p, y) -> float:
    p, y = np.clip(np.asarray(p, float), EPS, 1 - EPS), np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def roc_auc(p, y):
    """Mann-Whitney AUC with average ranks for ties; None when only one class is present."""
    p, y = np.asarray(p, float), np.asarray(y, int)
    pos, neg = int((y == 1).sum()), int((y == 0).sum())
    if pos == 0 or neg == 0:
        return None
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p))
    sp = p[order]
    i = 0
    while i < len(p):
        j = i
        while j + 1 < len(p) and sp[j + 1] == sp[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def reliability(p, y, bins=10) -> dict:
    """10-bin reliability table and expected calibration error (bin-weighted |mean prediction - observed rate|)."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    edges = np.linspace(0, 1, bins + 1)
    out, ece = [], 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & ((p < hi) if hi < 1 else (p <= hi))
        if m.any():
            out.append({"lo": round(lo, 2), "hi": round(hi, 2), "n": int(m.sum()), "mean_pred": float(p[m].mean()), "frac_pos": float(y[m].mean())})
            ece += m.sum() / len(p) * abs(p[m].mean() - y[m].mean())
    return {"bins": out, "ece": round(float(ece), 4)}


def summarize(p, y, with_reliability=False) -> dict:
    p, y = np.asarray(p, float), np.asarray(y, int)
    out = {"n": int(len(y)), "base_rate": float(y.mean()), "brier": brier(p, y), "log_loss": log_loss(p, y), "auc": roc_auc(p, y)}
    if with_reliability:
        out.update(reliability(p, y))
    return out
