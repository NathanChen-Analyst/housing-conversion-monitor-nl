"""Data quality as code: expectations per layer, a reconciliation check, and an HTML report.

Layers and what is asserted
---------------------------
staging  vbo_versions      schema & types, key uniqueness (id, version, registered_at), validity spans,
                           registration never before validity by more than a tolerance, pand_id exists
marts    conversion_events one event per dwelling, year within range, every event has a wijk
marts    wijk_year         grid completeness, suppression rule honoured, national total = sum of gemeente
external CBS               published yearly conversions within a tolerance of the CBS series (when given)

Every check returns a `Check` record; `run()` collects them, `report()` renders docs/quality.html.
A failing check with severity "error" makes `run()` return non-zero so a pipeline step can block publishing.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pandera.pandas as pa

from . import staging

# ------------------------------------------------------------------ schemas (pandera)

VboVersions = pa.DataFrameSchema(
    {
        "id": pa.Column(str, pa.Check.str_length(16, 16), nullable=False),
        "version": pa.Column(int, pa.Check.ge(1), nullable=False),
        "valid_from": pa.Column("datetime64[ns]", nullable=False, coerce=True),
        "valid_to": pa.Column("datetime64[ns]", nullable=True, coerce=True),
        "registered_at": pa.Column("datetime64[ns]", nullable=False, coerce=True),
        "registration_ended_at": pa.Column("datetime64[ns]", nullable=True, coerce=True),
        "status": pa.Column(str, nullable=False),
        "gebruiksdoel": pa.Column(str, nullable=True),
        "oppervlakte_m2": pa.Column(float, pa.Check.ge(0), nullable=True, coerce=True),
        "pand_id": pa.Column(str, nullable=True),
        "x": pa.Column(float, nullable=True, coerce=True),
        "y": pa.Column(float, nullable=True, coerce=True),
    },
    unique=["id", "version", "registered_at"],
    strict=False,
    name="vbo_versions",
)

ConversionEvents = pa.DataFrameSchema(
    {
        "vbo_id": pa.Column(str, nullable=False, unique=True),
        "wijk_code": pa.Column(str, nullable=False),
        "event_date": pa.Column("datetime64[ns]", nullable=False, coerce=True),
        "reg_date": pa.Column("datetime64[ns]", nullable=False, coerce=True),
    },
    strict=False,
    name="conversion_events",
)

WijkYear = pa.DataFrameSchema(
    {
        "wijk_code": pa.Column(str, nullable=False),
        "year": pa.Column(int, pa.Check.in_range(2000, 2100), nullable=False, coerce=True),
        "n": pa.Column(float, pa.Check.ge(0), nullable=True, coerce=True),
        "suppressed": pa.Column(bool, nullable=False, coerce=True),
    },
    unique=["wijk_code", "year"],
    strict=False,
    name="wijk_year",
)


# ------------------------------------------------------------------ check records


@dataclass
class Check:
    layer: str
    name: str
    passed: bool
    severity: str = "error"  # error | warn
    observed: str = ""
    expected: str = ""
    detail: str = ""


@dataclass
class QualityRun:
    started_at: str
    checks: list[Check] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(c.passed or c.severity == "warn" for c in self.checks)

    def add(self, *a, **k):
        self.checks.append(Check(*a, **k))


def _schema_check(run: QualityRun, layer: str, schema: pa.DataFrameSchema, df: pd.DataFrame) -> None:
    try:
        schema.validate(df, lazy=True)
        run.add(layer, f"schema:{schema.name}", True, observed=f"{len(df):,} rows", expected="conforms")
    except pa.errors.SchemaErrors as e:
        fc = e.failure_cases
        run.add(
            layer,
            f"schema:{schema.name}",
            False,
            observed=f"{len(fc)} failing cases",
            expected="conforms",
            detail=fc.head(10).to_string(),
        )


# ------------------------------------------------------------------ layer checks


def check_staging(run: QualityRun, staging_dir: Path, max_backdate_days: int = 3650) -> None:
    con = staging.connect(staging_dir)
    df = con.execute("SELECT * FROM vbo_versions").df()
    _schema_check(run, "staging", VboVersions, df)
    st = staging.version_table_stats(con)
    run.stats["staging"] = st
    run.add(
        "staging",
        "validity spans non-negative",
        st["negative_validity_spans"] == 0,
        observed=str(st["negative_validity_spans"]),
        expected="0",
    )
    lag = (df["registered_at"].dt.normalize() - df["valid_from"]).dt.days
    run.add(
        "staging",
        "registration lag within tolerance",
        bool((lag.abs() <= max_backdate_days).all()),
        severity="warn",
        observed=f"max |lag| = {int(lag.abs().max())} d, median = {int(lag.median())} d",
        expected=f"≤ {max_backdate_days} d",
    )
    if (staging_dir / "pand_versions").exists():
        orphans = con.execute("""SELECT count(DISTINCT v.pand_id) FROM vbo_versions v
                                 LEFT JOIN (SELECT DISTINCT id FROM pand_versions) p ON p.id = v.pand_id
                                 WHERE v.pand_id IS NOT NULL AND p.id IS NULL""").fetchone()[0]
        run.add(
            "staging",
            "every VBO references a known pand",
            orphans == 0,
            observed=f"{orphans} orphan pand_ids",
            expected="0",
        )
    con.close()


def check_events(run: QualityRun, events: pd.DataFrame, first_year: int, last_year: int) -> None:
    _schema_check(run, "marts", ConversionEvents, events)
    yrs = pd.to_datetime(events["event_date"]).dt.year
    bad = int(((yrs < first_year) | (yrs > last_year)).sum())
    run.add(
        "marts",
        "event years within window",
        bad == 0,
        observed=f"{bad} outside",
        expected=f"{first_year}–{last_year}",
    )
    nowijk = int(events["wijk_code"].isna().sum())
    run.add(
        "marts", "every event located in a wijk", nowijk == 0, observed=f"{nowijk} unlocated", expected="0"
    )
    run.stats["events"] = {"events": int(len(events)), "wijken": int(events["wijk_code"].nunique())}


def check_wijk_year(
    run: QualityRun, wijk_year: pd.DataFrame, gemeente_year: pd.DataFrame | None, suppress_below: int = 3
) -> None:
    _schema_check(run, "marts", WijkYear, wijk_year)
    wk, yr = wijk_year["wijk_code"].nunique(), wijk_year["year"].nunique()
    run.add(
        "marts",
        "wijk × year grid complete",
        len(wijk_year) == wk * yr,
        observed=f"{len(wijk_year):,} rows",
        expected=f"{wk} × {yr} = {wk * yr:,}",
    )
    leak = wijk_year[(wijk_year["n"] > 0) & (wijk_year["n"] < suppress_below) & (~wijk_year["suppressed"])]
    run.add(
        "marts",
        f"no published cell below {suppress_below}",
        len(leak) == 0,
        observed=f"{len(leak)} cells",
        expected="0",
    )
    if gemeente_year is not None:
        visible = float(wijk_year["n"].fillna(0).sum())
        total = float(gemeente_year["n"].sum())
        share = (total - visible) / total if total else 0
        run.add(
            "marts",
            "share hidden by suppression",
            share <= 0.15,
            severity="warn",
            observed=f"{share:.1%}",
            expected="≤ 15%",
        )
        run.stats["publication"] = {
            "national_total": int(total),
            "visible_in_map": int(visible),
            "hidden_share": round(share, 4),
        }


def check_against_cbs(run: QualityRun, ours: pd.Series, cbs: pd.Series, tolerance: float = 0.25) -> None:
    """ours/cbs: year → count. Flags years where |ours/cbs − 1| exceeds the tolerance."""
    j = pd.concat([ours.rename("ours"), cbs.rename("cbs")], axis=1).dropna()
    j["ratio"] = j["ours"] / j["cbs"]
    off = j[(j["ratio"] - 1).abs() > tolerance]
    run.add(
        "external",
        f"within ±{tolerance:.0%} of CBS per year",
        len(off) == 0,
        severity="warn",
        observed=f"{len(off)} of {len(j)} years outside; mean ratio {j['ratio'].mean():.2f}",
        expected="0 years outside",
        detail=j.round(2).to_string(),
    )
    run.stats["cbs"] = j.round(3).to_dict(orient="index")


# ------------------------------------------------------------------ run & report


def run(
    staging_dir: str | Path,
    events: pd.DataFrame | None = None,
    wijk_year: pd.DataFrame | None = None,
    gemeente_year: pd.DataFrame | None = None,
    cbs: pd.Series | None = None,
    first_year: int = 2012,
    last_year: int = 2024,
) -> QualityRun:
    qr = QualityRun(started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    check_staging(qr, Path(staging_dir))
    if events is not None:
        check_events(qr, events, first_year, last_year)
    if wijk_year is not None:
        check_wijk_year(qr, wijk_year, gemeente_year)
        if cbs is not None and gemeente_year is not None:
            ours = gemeente_year.groupby("year")["n"].sum()
            check_against_cbs(qr, ours, cbs)
    return qr


def report(
    qr: QualityRun, out_html: str | Path, out_json: str | Path | None = None, title: str = "Data quality"
) -> Path:
    rows = "\n".join(
        f'<tr class="{"ok" if c.passed else ("warn" if c.severity == "warn" else "fail")}">'
        f"<td>{c.layer}</td><td>{c.name}</td><td>{'pass' if c.passed else ('warn' if c.severity == 'warn' else 'FAIL')}</td>"
        f"<td>{c.observed}</td><td>{c.expected}</td></tr>"
        + (f'<tr class="detail"><td colspan="5"><pre>{c.detail}</pre></td></tr>' if c.detail else "")
        for c in qr.checks
    )
    stats = "\n".join(
        f"<h3>{k}</h3><pre>{json.dumps(v, indent=1, default=str)}</pre>" for k, v in qr.stats.items()
    )
    n_fail = sum(1 for c in qr.checks if not c.passed and c.severity == "error")
    n_warn = sum(1 for c in qr.checks if not c.passed and c.severity == "warn")
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · Housing Conversion Monitor NL</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:1000px;margin:32px auto;padding:0 16px;color:#1c2230;background:#fff}}
h1{{margin:0 0 4px}} .sub{{color:#6b7280;font-size:14px;margin-bottom:24px}}
.badge{{display:inline-block;padding:3px 10px;border-radius:999px;font-size:13px;font-weight:600;margin-right:8px}}
.b-ok{{background:#e6f4ec;color:#1e6b43}} .b-fail{{background:#fde8e4;color:#9a2f16}} .b-warn{{background:#fdf1dc;color:#8a5a00}}
table{{border-collapse:collapse;width:100%;font-size:14px}} th,td{{padding:8px 10px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top}}
th{{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#6b7280}}
tr.ok td:nth-child(3){{color:#1e6b43;font-weight:600}} tr.fail td:nth-child(3){{color:#9a2f16;font-weight:700}} tr.warn td:nth-child(3){{color:#8a5a00;font-weight:600}}
tr.detail td{{background:#fafafa}} pre{{margin:0;font-size:12px;white-space:pre-wrap}} h3{{font-size:13px;color:#6b7280;margin:24px 0 6px}}
</style></head><body>
<h1>{title}</h1>
<div class="sub">Run {qr.started_at} · <span class="badge {"b-ok" if qr.ok else "b-fail"}">{"all checks passed" if n_fail == 0 else f"{n_fail} failing"}</span>
{f'<span class="badge b-warn">{n_warn} warnings</span>' if n_warn else ""}</div>
<table><thead><tr><th>layer</th><th>check</th><th>result</th><th>observed</th><th>expected</th></tr></thead><tbody>{rows}</tbody></table>
{stats}
<p class="sub" style="margin-top:28px">Generated by <code>hcm quality</code> (src/hcm/quality.py). Checks: pandera schemas, SCD2 invariants, grid completeness, disclosure rule, CBS reconciliation.</p>
</body></html>"""
    out_html = Path(out_html)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")
    if out_json:
        Path(out_json).write_text(
            json.dumps(
                {
                    "started_at": qr.started_at,
                    "ok": qr.ok,
                    "checks": [asdict(c) for c in qr.checks],
                    "stats": qr.stats,
                },
                indent=1,
                default=str,
            ),
            encoding="utf-8",
        )
    return out_html
