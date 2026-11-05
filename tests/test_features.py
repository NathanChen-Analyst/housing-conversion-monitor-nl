"""Feature table: shape, lag logic, spatial lag, and the no-leakage guarantee."""

from datetime import date

import pandas as pd

from hcm import features as ft


def _inputs():
    conv = pd.DataFrame(
        {
            "vbo_id": ["a", "b", "c", "d"],
            "pand_id": ["p1", "p1", "p2", "p3"],
            "wijk_code": ["W1", "W1", "W1", "W2"],
            "pattern": ["use_change"] * 4,
            "event_date": [date(2020, 5, 1), date(2020, 9, 1), date(2021, 2, 1), date(2020, 6, 1)],
            # 'b' happened in 2020 but was only registered in March 2021 → must NOT count
            # as known at the 31 Dec 2020 forecast date
            "reg_date": [date(2020, 5, 3), date(2021, 3, 1), date(2021, 2, 2), date(2020, 6, 2)],
            "oppervlakte": [100.0, 110.0, 120.0, 90.0],
            "from_use": [None] * 4,
        }
    )
    years = [2020, 2021, 2022]
    stock = pd.DataFrame(
        [
            dict(
                wijk_code=w,
                year=y,
                nonres_vbo=50,
                nonres_floor_area=5000.0,
                nonres_share_1965_1995=0.4,
                office_vbo=30,
                retail_vbo=10,
                res_vbo=400,
            )
            for w in ["W1", "W2"]
            for y in years
        ]
    )
    cbs = pd.DataFrame(
        [
            dict(wijk_code=w, year=y, population=3000, density=4000, income_pp=30.0, woz_value=350)
            for w in ["W1", "W2"]
            for y in [2019] + years
        ]
    )
    nb = pd.DataFrame({"wijk_code": ["W1", "W2"], "nb_wijk_code": ["W2", "W1"]})
    return conv, stock, cbs, nb


def test_shape_and_target():
    conv, stock, cbs, nb = _inputs()
    f = ft.build(conv, stock, cbs, nb).set_index(["wijk_code", "year"])
    assert len(f) == 6
    assert f.loc[("W1", 2020), "n_conversions_next_year"] == 2  # a and b both happened in 2020
    assert f.loc[("W1", 2021), "n_conversions_next_year"] == 1
    assert f.loc[("W2", 2021), "n_conversions_next_year"] == 0


def test_lag_uses_registration_date_not_event_date():
    conv, stock, cbs, nb = _inputs()
    f = ft.build(conv, stock, cbs, nb).set_index(["wijk_code", "year"])
    # forecasting 2021 from the end of 2020: only 'a' was registered by then
    assert f.loc[("W1", 2021), "conversions_lag1"] == 1
    # forecasting 2022 from the end of 2021: both a and b are known for 2020 → lag3 picks both + c
    assert f.loc[("W1", 2022), "conversions_lag3"] == 3


def test_spatial_lag_reads_neighbour():
    conv, stock, cbs, nb = _inputs()
    f = ft.build(conv, stock, cbs, nb).set_index(["wijk_code", "year"])
    # W2's neighbour is W1, whose known lag1 for 2021 is 1
    assert f.loc[("W2", 2021), "nb_conversions_lag1"] == 1


def test_cbs_joined_from_previous_year():
    conv, stock, cbs, nb = _inputs()
    cbs.loc[(cbs.wijk_code == "W1") & (cbs.year == 2020), "population"] = 9999
    f = ft.build(conv, stock, cbs, nb).set_index(["wijk_code", "year"])
    assert f.loc[("W1", 2021), "population"] == 9999  # 2021 row sees 2020 CBS value
    assert f.loc[("W1", 2020), "population"] == 3000


def test_no_leakage_assertion_passes():
    conv, stock, cbs, nb = _inputs()
    f = ft.build(conv, stock, cbs, nb)
    ft.assert_no_leakage(f, conv)
