"""Generate placeholder docs/data/forecasts.json on a hex grid so the site renders
before real data exists. Run once; `hcm site` overwrites forecasts.json with real
output and the page switches to docs/data/wijken.geojson when that file is present.

    python docs/make_demo_data.py
"""

import json
import math
import random
from pathlib import Path

random.seed(20241105)
OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True)

# simplified mainland outline (lon, lat)
MAIN = [(6.83,53.45),(6.93,53.33),(7.21,53.18),(7.19,52.90),(7.06,52.87),(7.09,52.75),(6.74,52.66),(6.75,52.55),
        (7.03,52.38),(7.04,52.22),(6.83,51.95),(6.40,51.83),(6.10,51.87),(6.02,51.83),(6.00,51.70),(6.22,51.37),
        (6.10,51.19),(5.95,51.00),(6.08,50.87),(6.02,50.77),(5.98,50.75),(5.69,50.80),(5.60,50.85),(5.57,51.05),
        (5.60,51.25),(5.15,51.35),(4.93,51.44),(4.65,51.46),(4.37,51.37),(4.05,51.28),(3.80,51.22),(3.38,51.30),
        (3.38,51.38),(3.55,51.40),(3.57,51.44),(3.44,51.53),(3.60,51.60),(3.70,51.70),(3.87,51.82),(4.12,51.98),
        (4.27,52.10),(4.42,52.24),(4.53,52.38),(4.57,52.46),(4.62,52.62),(4.65,52.77),(4.75,52.96),(5.03,52.93),
        (5.33,53.07),(5.42,53.17),(5.90,53.38),(6.20,53.41),(6.50,53.45)]
IJ = [(5.03,52.93),(5.33,53.07),(5.42,52.98),(5.36,52.88),(5.70,52.84),(5.60,52.66),(5.43,52.55),(5.26,52.46),
      (5.10,52.38),(5.05,52.34),(4.98,52.38),(5.10,52.46),(5.07,52.64),(5.28,52.70),(5.10,52.77)]
CITIES = [("Amsterdam",4.90,52.37,1.0),("Rotterdam",4.48,51.92,.85),("Den Haag",4.31,52.08,.7),("Utrecht",5.12,52.09,.7),
          ("Eindhoven",5.47,51.44,.5),("Groningen",6.57,53.22,.4),("Tilburg",5.09,51.56,.3),("Almere",5.22,52.37,.3),
          ("Breda",4.78,51.59,.25),("Nijmegen",5.85,51.84,.3),("Arnhem",5.91,51.98,.3),("Haarlem",4.64,52.38,.25),
          ("Enschede",6.89,52.22,.25),("Amersfoort",5.39,52.16,.25),("Zwolle",6.09,52.51,.25),("Leiden",4.49,52.16,.25),
          ("Maastricht",5.69,50.85,.25),("Dordrecht",4.67,51.81,.2),("Leeuwarden",5.79,53.20,.2),("Apeldoorn",5.97,52.21,.2),
          ("'s-Hertogenbosch",5.30,51.70,.2),("Heerlen",5.98,50.89,.2),("Alkmaar",4.75,52.63,.12),("Venlo",6.17,51.37,.12)]


def cw(ring):
    """Return ring with clockwise (planar) winding: D3's geoPath fills the small side of a CW exterior ring."""
    area = sum((ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1]) for i in range(len(ring)))
    return list(ring) if area < 0 else list(reversed(ring))


def inside(poly, x, y):
    n, j, c = len(poly), len(poly) - 1, False
    for i in range(n):
        xi, yi = poly[i]; xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            c = not c
        j = i
    return c


# hex grid in lon/lat (roughly 4 km)
R = 0.045
dx, dy = math.sqrt(3) * R / math.cos(math.radians(52)) , 1.5 * R
cells = []
row = 0
lat = 50.72
while lat < 53.55:
    lon = 3.3 + (dx / 2 if row % 2 else 0)
    while lon < 7.25:
        if inside(MAIN, lon, lat) and not inside(IJ, lon, lat):
            cells.append((lon, lat))
        lon += dx
    lat += dy; row += 1

YEARS = list(range(2018, 2025))
features = []
areas = {}
for i, (lon, lat) in enumerate(cells):
    base, nearest, nd = 0.0, None, 1e9
    for name, cx, cy, w in CITIES:
        d = math.hypot((lon - cx) * 0.62, lat - cy) * 111
        base += w * math.exp(-(d * d) / (2 * 14 * 14))
        if d < nd: nd, nearest = d, name
    office = max(0, int(base * 2600 + random.random() * 300))
    dec = min(.75, max(.05, .18 + .28 * base + .18 * random.gauss(0, 1)))
    dist = max(.2, nd / 2 + random.random() * 2)
    price = int(2200 + 3200 * base + 400 * random.gauss(0, 1))
    code = f"WK{i:04d}"
    lag = max(0, int(base * 18 + random.random() * 2))
    f, a, drv = {}, {}, {}
    for y in YEARS:
        trend = .78 + .055 * (y - 2018) - (.08 if y >= 2023 else 0)
        mu = trend * (.0085 * office + 26 * dec - 1.4 * dist + .55 * lag + .0012 * (price - 2200))
        pred = max(0.0, mu)
        act = max(0, round(pred * (1 + .38 * random.gauss(0, 1)) + (25 * random.random() if random.random() < .04 else 0)))
        f[y], a[y] = round(pred, 1), act
        drv[y] = [["Non-residential stock", round(.0085 * office * trend, 1), f"{office} units"],
                  ["Share built 1965–95", round((26 * dec - 9) * trend, 1), f"{dec:.0%}"],
                  ["Distance to station", round(-1.4 * (dist - 4) * trend, 1), f"{dist:.1f} km"],
                  ["Conversions last year", round(.55 * (lag - 6) * trend, 1), str(lag)],
                  ["Price level", round(.0012 * (price - 3200) * trend, 1), f"€{price}/m²"]]
        lag = act
    areas[code] = {"name": f"{nearest} area", "forecast": f, "actual": a, "drivers": drv}
    # hexagon polygon for the fallback geometry
    pts = []
    for k in range(5, -1, -1):  # clockwise in lon/lat, which is what D3's spherical winding expects
        ang = math.radians(60 * k - 30)
        pts.append([round(lon + R / math.cos(math.radians(52)) * math.cos(ang), 4), round(lat + R * math.sin(ang), 4)])
    pts.append(pts[0])
    features.append({"type": "Feature", "properties": {"wijk_code": code, "name": f"{nearest} area"},
                     "geometry": {"type": "Polygon", "coordinates": [pts]}})

(OUT / "forecasts.json").write_text(json.dumps({
    "meta": {"unit": "wijk", "years": YEARS, "test_year": 2023, "synthetic": True,
             "headline": {"mae_vs_baseline": "−31%", "capture_at_200": "0.74", "events": "38.2M"}},
    "areas": areas}), encoding="utf-8")
(OUT / "demo_grid.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
(OUT / "outline.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"kind": "land"}, "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in cw(MAIN) + [cw(MAIN)[0]]]]}},
    {"type": "Feature", "properties": {"kind": "water"}, "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in cw(IJ) + [cw(IJ)[0]]]]}}]}), encoding="utf-8")
(OUT / "cities.json").write_text(json.dumps([{"name": n, "lon": x, "lat": y, "w": w} for n, x, y, w in CITIES]), encoding="utf-8")
print(f"wrote {len(cells)} demo cells to {OUT}")
