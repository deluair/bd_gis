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
    # numpy std defaults to population (ddof=0); the value cancels in the corrcoef ratio
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


def categorical_stats(pred_labels, ref_labels):
    """Overall accuracy and per-class user/producer accuracy."""
    if len(pred_labels) != len(ref_labels):
        raise ValueError("label lists must be the same length")
    if len(pred_labels) < 3:
        raise InsufficientData(f"need at least 3 samples, got {len(pred_labels)}")
    n = len(pred_labels)
    correct = sum(1 for p, r in zip(pred_labels, ref_labels) if p == r)
    labels = sorted(set(ref_labels) | set(pred_labels))
    per_class = {}
    for lab in labels:
        tp = sum(1 for p, r in zip(pred_labels, ref_labels) if p == lab and r == lab)
        pred_lab = sum(1 for p in pred_labels if p == lab)
        ref_lab = sum(1 for r in ref_labels if r == lab)
        per_class[lab] = {
            "user_acc": (tp / pred_lab) if pred_lab else 0.0,
            "producer_acc": (tp / ref_lab) if ref_lab else 0.0,
        }
    return {"overall_accuracy": correct / n, "n": n, "per_class": per_class}
