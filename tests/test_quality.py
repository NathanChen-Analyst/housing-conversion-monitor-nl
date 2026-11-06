"""Quality layer: schemas catch bad rows, suppression rule is enforced, report renders."""

import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from hcm import quality

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def staging_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("q")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "make_sample_data.py"), str(out)], check=True, cwd=ROOT
    )
    return out / "staging"


def test_staging_checks_pass_on_sample(staging_dir):
    qr = quality.run(staging_dir)
    names = {c.name: c for c in qr.checks}
    assert names["schema:vbo_versions"].passed
    assert names["validity spans non-negative"].passed
    assert names["every VBO references a known pand"].passed
    assert qr.ok


def test_suppression_rule_is_enforced():
    wy = pd.DataFrame(
        {
            "wijk_code": ["W1"] * 3 + ["W2"] * 3,
            "year": [2020, 2021, 2022] * 2,
            "n": [0, 2, 5, 1, 0, 9],
            "suppressed": [False, True, False, False, False, False],
        }
    )
    gy = pd.DataFrame({"year": [2020, 2021, 2022], "n": [1, 2, 14]})
    qr = quality.QualityRun(started_at="t")
    quality.check_wijk_year(qr, wy, gy)
    c = {x.name: x for x in qr.checks}
    assert c["wijk × year grid complete"].passed
    assert not c["no published cell below 3"].passed  # W2/2020 has n=1 unsuppressed
    assert not qr.ok


def test_events_schema_flags_duplicates(tmp_path):
    ev = pd.DataFrame(
        {
            "vbo_id": ["a", "a"],
            "wijk_code": ["W1", "W1"],
            "pand_id": ["p", "p"],
            "event_date": [date(2019, 1, 1)] * 2,
            "reg_date": [date(2019, 1, 2)] * 2,
        }
    )
    qr = quality.QualityRun(started_at="t")
    quality.check_events(qr, ev, 2012, 2024)
    assert not qr.checks[0].passed and "schema" in qr.checks[0].name


def test_cbs_reconciliation_and_report(tmp_path):
    ours = pd.Series({2019: 100, 2020: 90, 2021: 200})
    cbs = pd.Series({2019: 110, 2020: 95, 2021: 100})
    qr = quality.QualityRun(started_at="t")
    quality.check_against_cbs(qr, ours, cbs, tolerance=0.25)
    assert not qr.checks[0].passed and qr.checks[0].severity == "warn" and qr.ok  # warn does not block
    out = quality.report(qr, tmp_path / "q.html", tmp_path / "q.json")
    assert out.exists() and "within ±25% of CBS" in out.read_text()
