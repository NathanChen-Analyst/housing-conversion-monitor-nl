"""Generate a small, deterministic BAG-like sample so the whole pipeline runs without the real extract.

    python scripts/make_sample_data.py            # writes data/staging/*, data/raw/mutations/*

Shapes the real data has and the code must cope with: multiple versions per object, back-dated
registrations, superseded registrations, mixed gebruiksdoel strings, VBOs in old and new panden,
a few objects outside every buurt, and a monthly mutation file that repeats some rows already present.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

rng = np.random.default_rng(20241105)
N_PAND, YEAR0, YEAR1 = 1200, 2010, 2024
USES = ["kantoorfunctie", "winkelfunctie", "industriefunctie", "woonfunctie", "onderwijsfunctie"]


def d(y, m=1, day=1):
    return date(y, m, day)


def main(out_root: Path = ROOT / "data") -> None:
    pand_rows, vbo_rows = [], []
    for i in range(N_PAND):
        pid = f"0363100{i:09d}"
        bouwjaar = int(rng.integers(1900, 2016))
        x, y = rng.uniform(100_000, 180_000), rng.uniform(430_000, 500_000)  # RD New, roughly Randstad
        reg = d(YEAR0) + timedelta(days=int(rng.integers(0, 365)))
        pand_rows.append(
            dict(
                id=pid,
                version=1,
                valid_from=d(YEAR0),
                valid_to=None,
                registered_at=pd.Timestamp(reg),
                registration_ended_at=None,
                status="Pand in gebruik",
                bouwjaar=bouwjaar,
            )
        )
        n_vbo = int(rng.integers(1, 6))
        office = rng.random() < 0.3
        for k in range(n_vbo):
            vid = f"0363010{i:06d}{k:03d}"
            use0 = "kantoorfunctie" if office else str(rng.choice(USES))
            vreg = reg + timedelta(days=int(rng.integers(0, 60)))
            vbo_rows.append(
                dict(
                    id=vid,
                    version=1,
                    valid_from=d(YEAR0),
                    valid_to=None,
                    registered_at=pd.Timestamp(vreg),
                    registration_ended_at=None,
                    status="Verblijfsobject in gebruik",
                    gebruiksdoel=use0,
                    oppervlakte_m2=float(rng.integers(30, 400)),
                    pand_id=pid,
                    x=x,
                    y=y,
                )
            )
            # some offices convert to housing: a new version with woonfunctie, back-dated registration
            if office and rng.random() < 0.45:
                cy = int(rng.integers(2012, 2025))
                conv = d(cy, int(rng.integers(1, 13)), 1)
                lag = int(rng.integers(0, 240))
                vbo_rows[-1]["valid_to"] = conv
                vbo_rows.append(
                    dict(
                        id=vid,
                        version=2,
                        valid_from=conv,
                        valid_to=None,
                        registered_at=pd.Timestamp(conv + timedelta(days=lag)),
                        registration_ended_at=None,
                        status="Verblijfsobject in gebruik",
                        gebruiksdoel="woonfunctie",
                        oppervlakte_m2=float(rng.integers(30, 120)),
                        pand_id=pid,
                        x=x,
                        y=y,
                    )
                )
        # old office pand that gets new residential VBOs (new units in old pand)
        if office and bouwjaar < 1995 and rng.random() < 0.25:
            cy = int(rng.integers(2013, 2025))
            conv = d(cy, int(rng.integers(1, 13)), 1)
            for k in range(int(rng.integers(3, 12))):
                vid = f"0363010{i:06d}{k + 100:03d}"
                vbo_rows.append(
                    dict(
                        id=vid,
                        version=1,
                        valid_from=conv,
                        valid_to=None,
                        registered_at=pd.Timestamp(conv + timedelta(days=int(rng.integers(0, 120)))),
                        registration_ended_at=None,
                        status="Verblijfsobject in gebruik",
                        gebruiksdoel="woonfunctie",
                        oppervlakte_m2=float(rng.integers(40, 110)),
                        pand_id=pid,
                        x=x,
                        y=y,
                    )
                )
    pand = pd.DataFrame(pand_rows)
    vbo = pd.DataFrame(vbo_rows)
    # a superseded registration (correction): same version registered twice, first one ended
    fix = vbo.iloc[[5]].copy()
    fix["registration_ended_at"] = fix["registered_at"] + pd.Timedelta(days=3)
    fix2 = fix.copy()
    fix2["registered_at"] = fix2["registered_at"] + pd.Timedelta(days=3)
    fix2["registration_ended_at"] = None
    fix2["oppervlakte_m2"] = fix2["oppervlakte_m2"] + 1
    vbo = pd.concat([vbo.drop(index=5), fix, fix2], ignore_index=True)
    # a few points outside any buurt
    vbo.loc[vbo.index[:3], ["x", "y"]] = [[0.0, 0.0]] * 3

    for df in (pand, vbo):
        for c in ("valid_from", "valid_to"):
            df[c] = pd.to_datetime(df[c])
        for c in ("registered_at", "registration_ended_at"):
            df[c] = pd.to_datetime(df[c])

    import shutil

    stg = out_root / "staging"
    shutil.rmtree(stg, ignore_errors=True)  # a fresh sample: no leftover mutation partitions or ledger
    (stg / "vbo_versions").mkdir(parents=True, exist_ok=True)
    (stg / "pand_versions").mkdir(parents=True, exist_ok=True)
    vbo.to_parquet(stg / "vbo_versions" / "part-0.parquet", index=False)
    pand.to_parquet(stg / "pand_versions" / "part-0.parquet", index=False)

    # a "monthly mutation file": 40 new versions + 20 rows that already exist (must be no-ops)
    mut_dir = out_root / "raw" / "mutations"
    mut_dir.mkdir(parents=True, exist_ok=True)
    single = vbo[vbo["valid_to"].isna() & vbo["registration_ended_at"].isna()].drop_duplicates(
        "id", keep=False
    )
    new = single.sample(40, random_state=1).copy()
    new["version"] = new["version"] + 1
    new["valid_from"] = pd.Timestamp("2024-11-01")
    new["valid_to"] = pd.NaT
    new["registered_at"] = pd.Timestamp("2024-11-15")
    new["gebruiksdoel"] = "woonfunctie"
    dup = vbo.sample(20, random_state=2)
    pd.concat([new, dup]).to_parquet(mut_dir / "vbo_mutations_2024-11.parquet", index=False)

    # synthetic buurt polygons: a 10×10 grid over the sample area, two wijken per row, one gemeente
    import geopandas as gpd
    from shapely.geometry import box

    cells = []
    for r in range(10):
        for c in range(10):
            x0, y0 = 100_000 + c * 8_000, 430_000 + r * 7_000
            cells.append(
                dict(
                    BU_CODE=f"BU0363{r:02d}{c:02d}",
                    BU_NAAM=f"Buurt {r}{c}",
                    WK_CODE=f"WK0363{r:02d}",
                    GM_CODE="GM0363",
                    GM_NAAM="Sampleveld",
                    WATER="JA" if (r, c) == (9, 9) else "NEE",
                    geometry=box(x0, y0, x0 + 8_000, y0 + 7_000),
                )
            )
    gpd.GeoDataFrame(cells, crs="EPSG:28992").to_file(out_root / "raw" / "buurt_sample.gpkg", driver="GPKG")
    print(f"sample: {len(pand):,} pand versions, {len(vbo):,} vbo versions → {stg}; mutations → {mut_dir}")


if __name__ == "__main__":
    main()
