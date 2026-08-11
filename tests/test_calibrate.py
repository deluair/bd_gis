import math

import pytest

from validation.calibrate import (
    InsufficientData,
    ZeroVariance,
    bias,
    continuous_stats,
    mae,
    pearson_r,
    rmse,
)


def test_pearson_perfect_positive():
    assert pearson_r([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)


def test_mae_rmse_bias():
    assert mae([1, 2, 3], [1, 2, 4]) == pytest.approx(1 / 3)
    assert rmse([1, 2, 3], [1, 2, 4]) == pytest.approx(math.sqrt(1 / 3))
    assert bias([2, 2, 2], [1, 1, 1]) == pytest.approx(1.0)  # mean(pred - ref)


def test_continuous_stats_keys_and_n():
    s = continuous_stats([(2, 1), (4, 3), (6, 5)])
    assert set(s) == {"pearson_r", "mae", "rmse", "bias", "n"}
    assert s["n"] == 3


def test_insufficient_data_raises():
    with pytest.raises(InsufficientData):
        pearson_r([1, 2], [1, 2])


def test_zero_variance_raises():
    with pytest.raises(ZeroVariance):
        pearson_r([1, 1, 1], [1, 2, 3])


def test_categorical_overall_accuracy():
    from validation.calibrate import categorical_stats
    pred = ["water", "urban", "crop", "water"]
    ref = ["water", "urban", "urban", "water"]
    s = categorical_stats(pred, ref)
    assert s["overall_accuracy"] == pytest.approx(0.75)
    assert s["n"] == 4
    assert s["per_class"]["water"]["user_acc"] == pytest.approx(1.0)
    assert s["per_class"]["water"]["producer_acc"] == pytest.approx(1.0)


def test_categorical_insufficient_data_raises():
    from validation.calibrate import InsufficientData, categorical_stats
    with pytest.raises(InsufficientData):
        categorical_stats(["a", "b"], ["a", "b"])
