"""Unit tests for conversion detection on hand-built VBO histories."""

from datetime import date

import pandas as pd
import pytest

from hcm import conversions as cv

IN_USE = "Verblijfsobject in gebruik"


def ev(
    vbo,
    pand,
    begin,
    reg,
    use,
    bouwjaar=1975,
    status=IN_USE,
    pand_status=None,
    opp=100.0,
    wijk="WK001",
):
    return dict(
        vbo_id=vbo,
        pand_id=pand,
        begin_geldigheid=pd.Timestamp(begin),
        tijdstip_reg=pd.Timestamp(reg),
        status=status,
        gebruiksdoel=use,
        oppervlakte=opp,
        pand_bouwjaar=bouwjaar,
        pand_status=pand_status,
        wijk_code=wijk,
    )


def frame(rows):
    return pd.DataFrame(rows)


def test_simple_use_change_is_detected():
    df = frame(
        [
            ev("V1", "P1", "2015-01-01", "2015-01-05", "kantoorfunctie"),
            ev("V1", "P1", "2019-06-01", "2019-07-15", "woonfunctie"),
        ]
    )
    out = cv.detect(df)
    assert len(out) == 1
    r = out.iloc[0]
    assert r.pattern == "use_change"
    assert r.event_date == pd.Timestamp("2019-06-01")
    assert r.reg_date == pd.Timestamp("2019-07-15")  # registration date carried through
    assert r.from_use == "kantoorfunctie"


def test_always_residential_is_not_a_conversion():
    df = frame(
        [
            ev("V1", "P1", "2015-01-01", "2015-01-05", "woonfunctie"),
            ev("V1", "P1", "2018-01-01", "2018-01-05", "woonfunctie", opp=120.0),
        ]
    )
    assert len(cv.detect(df)) == 0


def test_flip_back_and_forth_counts_once_at_first_flip():
    df = frame(
        [
            ev("V1", "P1", "2014-01-01", "2014-01-02", "winkelfunctie"),
            ev("V1", "P1", "2016-01-01", "2016-01-02", "woonfunctie"),
            ev("V1", "P1", "2018-01-01", "2018-01-02", "winkelfunctie"),
            ev("V1", "P1", "2020-01-01", "2020-01-02", "woonfunctie"),
        ]
    )
    out = cv.detect(df)
    assert len(out) == 1
    assert out.iloc[0].event_date == pd.Timestamp("2016-01-01")


def test_mixed_use_string_is_parsed():
    df = frame(
        [
            ev("V1", "P1", "2015-01-01", "2015-01-02", "kantoorfunctie"),
            ev("V1", "P1", "2017-01-01", "2017-01-02", "kantoorfunctie,woonfunctie"),
        ]
    )
    out = cv.detect(df)
    assert len(out) == 1 and out.iloc[0].pattern == "use_change"


def test_same_day_versions_are_ordered_by_registration():
    # two versions valid from the same day; registration order decides which is "previous"
    df = frame(
        [
            ev("V1", "P1", "2016-03-01", "2016-03-01", "kantoorfunctie"),
            ev("V1", "P1", "2016-03-01", "2016-03-09", "woonfunctie"),
        ]
    )
    out = cv.detect(df)
    assert len(out) == 1
    assert out.iloc[0].reg_date == pd.Timestamp("2016-03-09")


def test_new_unit_in_old_pand():
    # office pand from 1980 with one office VBO; in 2020 three new residential VBOs appear
    rows = [ev("O1", "P9", "2012-01-01", "2012-01-02", "kantoorfunctie", bouwjaar=1980)]
    rows += [
        ev(f"R{i}", "P9", "2020-05-01", "2020-05-20", "woonfunctie", bouwjaar=1980)
        for i in range(3)
    ]
    out = cv.detect(frame(rows))
    assert set(out.pattern) == {"new_unit_in_old_pand"}
    assert len(out) == 3


def test_new_build_is_not_a_conversion():
    # pand built 2020, residential VBOs appear 2020: that's new construction, not a conversion
    rows = [
        ev(f"R{i}", "P2", "2020-09-01", "2020-09-10", "woonfunctie", bouwjaar=2020)
        for i in range(4)
    ]
    assert len(cv.detect(frame(rows))) == 0


def test_old_pand_without_prior_nonres_is_not_a_conversion():
    # an old pand that never had a non-residential VBO in the data (e.g. subdivision of a house)
    rows = [
        ev("R0", "P3", "2010-01-01", "2010-01-02", "woonfunctie", bouwjaar=1930),
        ev("R1", "P3", "2021-01-01", "2021-01-02", "woonfunctie", bouwjaar=1930),
    ]
    assert len(cv.detect(frame(rows))) == 0


def test_after_verbouwing_pattern():
    rows = [
        ev(
            "O1",
            "P5",
            "2010-01-01",
            "2010-01-02",
            "kantoorfunctie",
            bouwjaar=1990,
            pand_status="Pand in gebruik",
        ),
        ev(
            "O1",
            "P5",
            "2018-01-01",
            "2018-01-02",
            "kantoorfunctie",
            bouwjaar=1990,
            pand_status="Verbouwing pand",
        ),
        ev(
            "R1",
            "P5",
            "2019-06-01",
            "2019-06-02",
            "woonfunctie",
            bouwjaar=1990,
            pand_status="Pand in gebruik",
        ),
    ]
    out = cv.detect(frame(rows), patterns=("after_verbouwing",))
    assert len(out) == 1 and out.iloc[0].pattern == "after_verbouwing"


def test_one_row_per_vbo_when_several_patterns_fire():
    # R1 qualifies as new_unit_in_old_pand AND after_verbouwing → exactly one row
    rows = [
        ev(
            "O1",
            "P6",
            "2010-01-01",
            "2010-01-02",
            "kantoorfunctie",
            bouwjaar=1985,
            pand_status="Pand in gebruik",
        ),
        ev(
            "O1",
            "P6",
            "2018-01-01",
            "2018-01-02",
            "kantoorfunctie",
            bouwjaar=1985,
            pand_status="Verbouwing pand",
        ),
        ev(
            "R1",
            "P6",
            "2019-06-01",
            "2019-06-02",
            "woonfunctie",
            bouwjaar=1985,
            pand_status="Pand in gebruik",
        ),
    ]
    out = cv.detect(frame(rows))
    assert len(out) == 1
    assert out.iloc[0].pattern == "new_unit_in_old_pand"  # priority order


def test_missing_column_raises():
    with pytest.raises(ValueError):
        cv.detect(pd.DataFrame({"vbo_id": ["x"]}))


def test_aggregate_and_registered_before():
    conv = pd.DataFrame(
        {
            "vbo_id": ["a", "b", "c"],
            "pand_id": ["p", "p", "q"],
            "wijk_code": ["W1", "W1", "W2"],
            "pattern": ["use_change"] * 3,
            "event_date": [date(2019, 3, 1), date(2019, 11, 1), date(2020, 2, 1)],
            "reg_date": [date(2019, 3, 5), date(2020, 4, 1), date(2020, 2, 3)],  # b registered late
            "oppervlakte": [80.0, 90.0, 100.0],
            "from_use": [None] * 3,
        }
    )
    agg = cv.aggregate(conv)
    assert agg.set_index(["wijk_code", "period"]).loc[("W1", 2019), "n_conversions"] == 2
    # as of 31 Dec 2019 the register only knew about 'a'
    known = cv.registered_before(conv, "2019-12-31")
    assert list(known.vbo_id) == ["a"]
