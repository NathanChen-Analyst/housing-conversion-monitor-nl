"""SCD2 snapshots and idempotent mutation merge, on the synthetic sample."""

import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from hcm import mutations, staging

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "make_sample_data.py")],
        check=True,
        env={"PYTHONPATH": str(ROOT / "src")},
        cwd=ROOT,
    )
    # the script writes to ROOT/data; copy to an isolated folder so tests never mutate the repo copy
    shutil.copytree(ROOT / "data" / "staging", out / "staging")
    shutil.copytree(ROOT / "data" / "raw" / "mutations", out / "mutations")
    return out


def test_snapshot_validity_vs_registration(sample):
    con = staging.connect(sample / "staging")
    v = staging.snapshot(con, "2019-01-01", by="validity")
    k = staging.snapshot(con, "2019-01-01", by="registration")
    assert v["id"].is_unique and k["id"].is_unique
    # the register always knows less than (or as much as) what was true, never more
    assert len(k) <= len(v)
    # a version valid from 2019-06 must not be in a 2019-01 snapshot
    assert (v["valid_from"] <= pd.Timestamp("2019-01-01")).all()


def test_superseded_registration_is_hidden(sample):
    con = staging.connect(sample / "staging")
    v = staging.snapshot(con, "2024-12-31", by="validity")
    # the sample contains one corrected registration; the snapshot keeps only the latest copy
    dup = v.groupby(["id", "version"]).size()
    assert (dup == 1).all()


def test_yearly_snapshots_stack(sample):
    con = staging.connect(sample / "staging")
    st = staging.yearly_snapshots(con, [2015, 2020])
    assert set(st["year"]) == {2015, 2020}
    assert not st.duplicated(["year", "id"]).any()


def test_mutation_merge_is_idempotent(sample):
    stg = sample / "staging"
    before = staging.snapshot(staging.connect(stg), "2024-12-31")
    r1 = mutations.apply_mutation_file(sample / "mutations" / "vbo_mutations_2024-11.parquet", stg)
    assert r1["status"] == "applied" and r1["rows_new"] == 40 and r1["rows_superseded"] == 0
    after1 = staging.snapshot(staging.connect(stg), "2024-12-31")
    # 40 new versions supersede 40 old ones within the same objects: same number of objects, use changed
    assert len(after1) == len(before)
    changed = after1.merge(before, on="id", suffixes=("", "_old"))
    assert (changed["version"] >= changed["version_old"]).all()
    assert (changed["version"] > changed["version_old"]).sum() == 40

    r2 = mutations.apply_mutation_file(sample / "mutations" / "vbo_mutations_2024-11.parquet", stg)
    assert r2["status"] == "already_applied"
    after2 = staging.snapshot(staging.connect(stg), "2024-12-31")
    pd.testing.assert_frame_equal(
        after1.sort_values("id").reset_index(drop=True), after2.sort_values("id").reset_index(drop=True)
    )
    ledger = pd.read_parquet(stg / mutations.LEDGER)
    assert len(ledger) == 1


def test_stats(sample):
    s = staging.version_table_stats(staging.connect(sample / "staging"))
    assert s["versions"] >= s["objects"] > 0
    assert s["negative_validity_spans"] == 0
