"""Geography helpers: BAG point parsing, assignment to CBS buurt/wijk, boundary export.

All history is assigned to ONE boundary vintage (see config.yaml → space.reference_year),
so municipal mergers and redrawn wijken never break the panel.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

RD_NEW = "EPSG:28992"
KEEP = ["BU_CODE", "BU_NAAM", "WK_CODE", "GM_CODE", "GM_NAAM", "geometry"]


def load_buurten(shp: str | Path, land_only: bool = True) -> gpd.GeoDataFrame:
    """CBS Wijk- en buurtkaart shapefile → buurt polygons with the code columns the pipeline needs."""
    g = gpd.read_file(shp)
    if land_only and "WATER" in g.columns:
        g = g[g["WATER"] == "NEE"]
    return g[KEEP].copy()


def parse_point(val) -> Point | None:
    """'x y [z]' string (BAG Geometrie column) → shapely Point, or None if unparsable."""
    try:
        parts = str(val).split()
        return Point(float(parts[0]), float(parts[1])) if len(parts) >= 2 else None
    except (ValueError, IndexError):
        return None


def to_points(df: pd.DataFrame, geom_col: str = "Geometrie", crs: str = RD_NEW) -> gpd.GeoDataFrame:
    """BAG geometry-string column → GeoDataFrame of points; rows that fail to parse are dropped."""
    pts = df[geom_col].map(parse_point)
    ok = pts.notna()
    return gpd.GeoDataFrame(df[ok].copy(), geometry=pts[ok].to_numpy(), crs=crs)


def assign_areas(points: gpd.GeoDataFrame, buurten: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Point-in-polygon: attach BU/WK/GM codes to every point. Points outside all buurten get NaN codes."""
    if points.crs != buurten.crs:
        points = points.to_crs(buurten.crs)
    out = gpd.sjoin(points, buurten, how="left", predicate="within")
    return out.drop(columns=["index_right"], errors="ignore")


def wijk_boundaries(buurten: gpd.GeoDataFrame, simplify_m: float = 50) -> gpd.GeoDataFrame:
    """Dissolve buurten to wijken; simplify (metres, in RD) to keep the web file small."""
    w = buurten.dissolve(by="WK_CODE", aggfunc={"GM_CODE": "first", "GM_NAAM": "first"}).reset_index()
    w["geometry"] = w.geometry.simplify(simplify_m, preserve_topology=True)
    return w


def export_wijk_geojson(buurten: gpd.GeoDataFrame, out_path: str | Path, simplify_m: float = 50) -> Path:
    """Write wijken as WGS84 GeoJSON with `wijk_code` + `name`, ready for docs/data/wijken.geojson."""
    w = wijk_boundaries(buurten, simplify_m).to_crs(4326)
    w = w.rename(columns={"WK_CODE": "wijk_code"})
    w["name"] = w["GM_NAAM"]
    out_path = Path(out_path)
    w[["wijk_code", "name", "geometry"]].to_file(out_path, driver="GeoJSON")
    return out_path
