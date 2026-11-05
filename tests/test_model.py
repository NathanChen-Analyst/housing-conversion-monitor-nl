"""Model plumbing: time split, metrics, and that every model beats nothing on synthetic data."""

import numpy as np
import pandas as pd

from hcm import model as md


def _panel(n_areas=300, years=range(2016, 2025), seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for a in range(n_areas):
        stock = rng.integers(5, 400)
        share = rng.uniform(0.05, 0.7)
        lag = rng.poisson(1)
        for y in years:
            mu = 0.01 * stock + 4 * share + 0.5 * lag
            target = rng.poisson(mu)
            rows.append(
                dict(
                    wijk_code=f"W{a:04d}",
                    year=y,
                    nonres_stock=stock,
                    nonres_share_1965_1995=share,
                    conversions_lag1=lag,
                    baseline_seasonal_naive=lag,
                    n_conversions_next_year=target,
                )
            )
            lag = target
    return pd.DataFrame(rows)


def test_split_is_strictly_by_time():
    df = _panel()
    tr, va, te = md.split(df, 2022, 2023, 2024)
    assert tr.year.max() == 2022 and set(va.year) == {2023} and set(te.year) == {2024}
    assert len(tr) + len(va) + len(te) == len(df)


def test_metrics_behave():
    y = np.array([0, 1, 2, 10])
    p = y.astype(float)
    assert md.mae(y, p) == 0
    assert md.poisson_deviance(y, p) < 1e-6
    assert md.spearman(y, p) == 1.0
    assert md.precision_at_k(y, p, 1) == 10 / 13


def test_models_beat_baseline_on_synthetic_panel():
    df = _panel()
    res = md.run_all(df, 2022, 2023, 2024, monotone={"nonres_stock": 1}, k=30)
    test = res[res.split == "test"].set_index("model")
    assert test.loc["lgbm_tweedie", "mae"] < test.loc["seasonal_naive", "mae"]
    assert test.loc["nb_glm", "mae"] < test.loc["seasonal_naive", "mae"]
