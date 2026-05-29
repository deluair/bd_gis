"""Pure agreement statistics for indicator validation. No I/O, no bd_gis imports."""
import numpy as np


class InsufficientData(ValueError):
    pass


class ZeroVariance(ValueError):
    pass


def _check(x, y):
    if len(x) != len(y):
        raise ValueError("x and y must be the same length")
    if len(x) < 3:
        raise InsufficientData(f"need at least 3 pairs, got {len(x)}")


def pearson_r(x, y):
    _check(x, y)
    ax, ay = np.asarray(x, float), np.asarray(y, float)
    if ax.std() == 0 or ay.std() == 0:
        raise ZeroVariance("zero variance in x or y")
    return float(np.corrcoef(ax, ay)[0, 1])


def mae(x, y):
    _check(x, y)
    return float(np.mean(np.abs(np.asarray(x, float) - np.asarray(y, float))))


def rmse(x, y):
    _check(x, y)
    d = np.asarray(x, float) - np.asarray(y, float)
    return float(np.sqrt(np.mean(d * d)))


def bias(x, y):
    """Mean signed error, mean(predicted - reference)."""
    _check(x, y)
    return float(np.mean(np.asarray(x, float) - np.asarray(y, float)))


def continuous_stats(pairs):
    """pairs: list of (predicted, reference). Returns dict of stats."""
    pred = [p for p, _ in pairs]
    ref = [r for _, r in pairs]
    return {
        "pearson_r": pearson_r(pred, ref),
        "mae": mae(pred, ref),
        "rmse": rmse(pred, ref),
        "bias": bias(pred, ref),
        "n": len(pairs),
    }
