"""One-shot: BAG office→housing events  →  public wijk×year files + wijk boundaries for the site.

Edit the three paths, then run in the environment where the events DataFrame can be loaded:

    python scripts/make_public_data.py

or paste the body into a notebook cell where `df_vbos_in_pands_with_office_disappear` already exists.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hcm import geo  # noqa: E402
from hcm.export_public import export_public  # noqa: E402

# ------------------------------------------------------------------ paths (edit)
EVENTS_PARQUET = (
    "/scratch/p305121/.../df_vbos_in_pands_with_office_disappear.parquet"  # or load however you do
)
BUURT_SHP = "/scratch/p305121/cbs/map/WijkBuurtkaart_2012_v3/buurt_2012.shp"  # reference vintage
SAVE_DIR = "/scratch/p305121/public_export"
# ------------------------------------------------------------------

df = pd.read_parquet(EVENTS_PARQUET)
df = df[df["new_unit"]]  # conversion event rows only

buurten = geo.load_buurten(BUURT_SHP)  # land buurten, 2012 vintage
events = geo.assign_areas(geo.to_points(df), buurten)  # + BU/WK/GM codes

print(export_public(events, SAVE_DIR))  # 4 files + summary
geo.export_wijk_geojson(buurten, Path(SAVE_DIR) / "wijken.geojson")

print("\nCopy to the site (docs/data/):")
print(f"  {SAVE_DIR}/wijk_year_conversions.json")
print(f"  {SAVE_DIR}/wijken.geojson")
