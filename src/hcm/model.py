"""Train and evaluate the forecast: seasonal-naive baseline, NB GLM, LightGBM-Tweedie.

Time-based split only. Rows with year <= train_until train; validate_year tunes;
test_year is touched once at the end.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

ID_COLS = ["wijk_code", "year"]
TARGET = "n_conversions_next_year"
BASELINE = "baseline_seasonal_naive"


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in ID_COLS + [TARGET, BASELINE]]


def split(df: pd.DataFrame, train_until: int, validate_year: int, test_year: int):
    tr = df[df.year <= train_until]
    va = df[df.year == validate_year]
    te = df[df.year == test_year]
    return tr, va, te


# ---------------------------------------------------------------- metrics


def mae(y, p):
    return float(np.mean(np.abs(np.asarray(y) - np.asarray(p))))


def poisson_deviance(y, p, eps=1e-9):
    y = np.asarray(y, float)
    p = np.clip(np.asarray(p, float), eps, None)
    safe_y = np.where(y > 0, y, 1.0)  # avoid log(0); masked out below
    term = np.where(y > 0, y * np.log(safe_y / p), 0.0)
    return float(2 * np.mean(term - (y - p)))


def spearman(y, p):
    return float(pd.Series(y).rank().corr(pd.Series(p).rank()))


def precision_at_k(y, p, k: int):
    """Of the k areas ranked highest by the forecast, what share of actual conversions do they hold?"""
    y = np.asarray(y, float)
    p = np.asarray(p, float)
    if y.sum() == 0:
        return float("nan")
    top = np.argsort(-p)[:k]
    return float(y[top].sum() / y.sum())


def evaluate(y, p, k: int = 200) -> dict:
    return {
        "mae": mae(y, p),
        "poisson_dev": poisson_deviance(y, p),
        "spearman": spearman(y, p),
        f"capture_at_{k}": precision_at_k(y, p, k),
    }


# ---------------------------------------------------------------- models


@dataclass
class Fitted:
    name: str
    predict: callable
    info: dict = field(default_factory=dict)


def fit_baseline(train: pd.DataFrame) -> Fitted:
    return Fitted("seasonal_naive", lambda df: df[BASELINE].to_numpy(float))


def fit_glm(train: pd.DataFrame, cols: list[str]) -> Fitted:
    import statsmodels.api as sm

    X = sm.add_constant(train[cols].fillna(0.0).astype(float))
    y = train[TARGET].astype(float)
    # Negative binomial handles the over-dispersion that Poisson would understate.
    res = sm.GLM(y, X, family=sm.families.NegativeBinomial(alpha=1.0)).fit()

    def predict(df):
        Xn = sm.add_constant(df[cols].fillna(0.0).astype(float), has_constant="add")
        return np.asarray(res.predict(Xn))

    return Fitted("nb_glm", predict, {"params": res.params.to_dict()})


def fit_lgbm(
    train: pd.DataFrame,
    cols: list[str],
    monotone: dict[str, int] | None = None,
    tweedie_power: float = 1.4,
    **kw,
) -> Fitted:
    import lightgbm as lgb

    mono = [int((monotone or {}).get(c, 0)) for c in cols]
    params = dict(
        objective="tweedie",
        tweedie_variance_power=tweedie_power,
        learning_rate=0.03,
        num_leaves=31,
        min_data_in_leaf=40,
        feature_fraction=0.8,
        bagging_fraction=0.8,
        bagging_freq=1,
        lambda_l2=1.0,
        monotone_constraints=mono,
        verbose=-1,
        seed=7,
    )
    params.update(kw)
    ds = lgb.Dataset(train[cols], train[TARGET])
    booster = lgb.train(params, ds, num_boost_round=kw.pop("num_boost_round", 600))
    return Fitted("lgbm_tweedie", lambda df: booster.predict(df[cols]), {"booster": booster})


def run_all(
    df: pd.DataFrame,
    train_until: int,
    validate_year: int,
    test_year: int,
    monotone: dict | None = None,
    k: int = 200,
) -> pd.DataFrame:
    """Fit every model on train, report metrics on validate and test. Returns a tidy table."""
    cols = feature_columns(df)
    tr, va, te = split(df, train_until, validate_year, test_year)
    models = [fit_baseline(tr), fit_glm(tr, cols), fit_lgbm(tr, cols, monotone)]
    rows = []
    for m in models:
        for name, part in [("validate", va), ("test", te)]:
            if len(part) == 0:
                continue
            met = evaluate(part[TARGET], m.predict(part), k=k)
            rows.append({"model": m.name, "split": name, **met})
    return pd.DataFrame(rows)
