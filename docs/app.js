/* Housing Conversion Monitor NL — map page.
 * Reads:
 *   data/forecasts.json   {meta:{years,test_year,synthetic,headline}, areas:{code:{name,forecast,actual,drivers}}}
 *   data/wijken.geojson   real boundaries (features need properties.wijk_code; optional properties.name)
 *   data/demo_grid.geojson fallback hex grid when wijken.geojson is absent
 *   data/outline.geojson  land/water outline drawn behind the areas
 *   data/cities.json      labels
 * Swap in real data by writing forecasts.json (hcm site) and dropping wijken.geojson in docs/data/.
 */
(async function () {
  const W = 640, H = 720;
  const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const $ = id => document.getElementById(id);

  async function loadJSON(url) { const r = await fetch(url); if (!r.ok) throw new Error(url); return r.json(); }
  async function loadFirst(urls) { for (const u of urls) { try { return [u, await loadJSON(u)]; } catch (e) { /* next */ } } return [null, null]; }

  const fc = await loadJSON("data/forecasts.json");
  const [geoUrl, geo] = await loadFirst(["data/wijken.geojson", "data/demo_grid.geojson"]);
  const outline = await loadJSON("data/outline.geojson").catch(() => null);
  const cities = await loadJSON("data/cities.json").catch(() => []);
  if (!geo) { $("panel").innerHTML = '<div class="empty">No geometry found in data/.</div>'; return; }

  // D3 uses spherical winding: an exterior ring that is counter-clockwise in lon/lat is read as
  // "the whole globe minus this polygon". Rewind exterior rings to clockwise and holes to counter-clockwise
  // so a wijken.geojson exported from any GIS tool renders correctly.
  function ringArea(r) { let a = 0; for (let i = 0; i < r.length - 1; i++) a += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1]; return a; }
  function rewind(fcoll) {
    for (const f of fcoll.features) {
      const g = f.geometry; if (!g) continue;
      const polys = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
      for (const poly of polys) poly.forEach((ring, i) => { const a = ringArea(ring); if ((i === 0 && a > 0) || (i > 0 && a < 0)) ring.reverse(); });
    }
    return fcoll;
  }
  rewind(geo); if (outline) rewind(outline);

  const synthetic = !!fc.meta.synthetic || geoUrl.endsWith("demo_grid.geojson");
  $("demo-pill").hidden = !synthetic;
  if (fc.meta.unit) $("unit-label").textContent = fc.meta.unit;

  const YEARS = fc.meta.years.map(Number);
  const yearInput = $("year");
  yearInput.min = YEARS[1]; yearInput.max = YEARS[YEARS.length - 1]; yearInput.value = yearInput.max;
  let year = +yearInput.value, mode = "pred", selected = null;
  $("year-out").textContent = year;

  // join geometry ↔ forecasts
  const feats = geo.features.filter(f => fc.areas[f.properties.wijk_code]);
  for (const f of feats) { const a = fc.areas[f.properties.wijk_code]; f.a = a; f.code = f.properties.wijk_code; f.name = f.properties.name || a.name || f.code; }
  const val = (f) => { const p = +f.a.forecast[year] || 0, a = +f.a.actual[year] || 0; return mode === "pred" ? p : mode === "act" ? a : a - p; };

  // headline numbers
  const hl = fc.meta.headline || {};
  $("s-mae").textContent = hl.mae_vs_baseline ?? "—";
  $("s-cap").textContent = hl.capture_at_200 ?? "—";
  $("s-ev").textContent = hl.events ?? "—";

  // ---------- projection & layers ----------
  const proj = d3.geoMercator().fitExtent([[18, 18], [W - 18, H - 18]], outline || geo);
  const path = d3.geoPath(proj);
  const svg = d3.select("#map"), g = svg.append("g");
  if (outline) {
    g.selectAll("path.bg").data(outline.features).join("path")
      .attr("class", d => d.properties.kind === "water" ? "water" : "land").attr("d", path);
  }
  const areaSel = g.append("g").selectAll("path").data(feats).join("path")
    .attr("class", "area").attr("d", path)
    .on("pointermove", (e, d) => showTip(e, d)).on("pointerleave", hideTip)
    .on("click", (e, d) => select(d));
  const cityG = g.append("g").attr("pointer-events", "none");
  const big = cities.filter(c => c.w >= 0.2).map(c => ({ ...c, xy: proj([c.lon, c.lat]) }));
  cityG.selectAll("circle").data(big).join("circle").attr("class", "city").attr("cx", d => d.xy[0]).attr("cy", d => d.xy[1]).attr("r", 1.8);
  cityG.selectAll("text").data(big).join("text").attr("class", "city-label").attr("x", d => d.xy[0] + 4).attr("y", d => d.xy[1] + 3).text(d => d.name);

  const zoom = d3.zoom().scaleExtent([1, 12]).on("zoom", (e) => {
    g.attr("transform", e.transform);
    cityG.selectAll("text").style("font-size", (9.5 / Math.sqrt(e.transform.k)) + "px");
  });
  svg.call(zoom);
  $("z-in").onclick = () => svg.transition().call(zoom.scaleBy, 1.6);
  $("z-out").onclick = () => svg.transition().call(zoom.scaleBy, 1 / 1.6);
  $("z-reset").onclick = () => svg.transition().call(zoom.transform, d3.zoomIdentity);

  // ---------- colour ----------
  const seq = () => d3.scaleLinear().domain([0, .2, .4, .6, .8, 1]).range([0, 1, 2, 3, 4, 5].map(i => css(`--seq-${i}`))).interpolate(d3.interpolateLab);
  const div = () => d3.scaleLinear().domain([-1, 0, 1]).range([css("--div-neg"), css("--div-mid"), css("--div-pos")]).interpolate(d3.interpolateLab);

  function paint() {
    const vals = feats.map(val);
    let scale, lo, hi;
    if (mode === "err") { const m = d3.quantile(vals.map(Math.abs).sort(d3.ascending), 0.97) || 1; lo = -m; hi = m; const s = div(); scale = v => s(Math.max(-1, Math.min(1, v / m))); }
    else { lo = 0; hi = d3.quantile(vals.slice().sort(d3.ascending), 0.98) || 1; const s = seq(); scale = v => s(Math.min(1, v / hi)); }
    areaSel.attr("fill", d => scale(val(d)));
    $("lg-bar").style.background = `linear-gradient(90deg, ${d3.range(0, 1.001, 0.1).map(t => scale(lo + t * (hi - lo))).join(",")})`;
    $("lg-title").textContent = { pred: "Forecast conversions", act: "Actual conversions", err: "Actual − forecast" }[mode] + " · " + year;
    $("lg-min").textContent = mode === "err" ? Math.round(lo) : "0";
    $("lg-max").textContent = (mode === "err" ? "+" : "≥") + Math.round(hi);
    $("s-total").textContent = d3.format(",")(Math.round(d3.sum(feats, f => +f.a.forecast[year] || 0)));
    document.querySelectorAll(".yr-txt").forEach(el => el.textContent = year);
    if (selected) renderPanel(selected);
    renderList();
  }
  for (const [id, m] of [["m-pred", "pred"], ["m-act", "act"], ["m-err", "err"]]) {
    $(id).onclick = () => { mode = m; document.querySelectorAll(".seg button").forEach(b => b.setAttribute("aria-pressed", "false")); $(id).setAttribute("aria-pressed", "true"); paint(); };
  }
  yearInput.oninput = () => { year = +yearInput.value; $("year-out").textContent = year; paint(); };
  if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", paint);

  // ---------- tooltip ----------
  const tip = $("tip"), box = $("mapbox");
  function showTip(e, d) {
    const r = box.getBoundingClientRect();
    tip.style.left = (e.clientX - r.left) + "px"; tip.style.top = (e.clientY - r.top) + "px";
    tip.innerHTML = `${d.name} · ${d.code}<br>forecast <b>${(+d.a.forecast[year] || 0).toFixed(0)}</b> · actual <b>${+d.a.actual[year] || 0}</b>`;
    tip.style.opacity = 1;
  }
  function hideTip() { tip.style.opacity = 0; }

  // ---------- panel ----------
  function select(d) {
    selected = d; areaSel.classed("sel", f => f === d); renderPanel(d);
    if (window.innerWidth < 900) $("panel").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function drivers(d) { const dr = (d.a.drivers || {})[year] || []; return dr.slice().sort((x, y) => Math.abs(y[1]) - Math.abs(x[1])); }
  function renderPanel(d) {
    const p = +d.a.forecast[year] || 0, a = +d.a.actual[year] || 0, mx = Math.max(p, a, 1);
    const drv = drivers(d).slice(0, 4), dm = Math.max(...drv.map(x => Math.abs(x[1])), 1);
    const tsW = 300, tsH = 110, mL = 28, mR = 8, mT = 8, mB = 20;
    const xs = d3.scaleLinear().domain(d3.extent(YEARS)).range([mL, tsW - mR]);
    const ymax = Math.max(1, d3.max(YEARS, y => Math.max(+d.a.forecast[y] || 0, +d.a.actual[y] || 0)));
    const ys = d3.scaleLinear().domain([0, ymax]).nice().range([tsH - mB, mT]);
    const line = key => d3.line().x(y => xs(y)).y(y => ys(+d.a[key][y] || 0))(YEARS);
    const ticks = ys.ticks(3), testX = xs(fc.meta.test_year) - (xs(YEARS[1]) - xs(YEARS[0])) / 2;
    $("panel").innerHTML = `
      <div><h2>${d.name}</h2><div class="where">${d.code} · ${year}</div></div>
      <div class="pa">
        <span class="k">Forecast</span><span class="bar"><i style="width:${100 * p / mx}%;background:var(--accent)"></i></span><span class="n">${p.toFixed(0)}</span>
        <span class="k">Actual</span><span class="bar"><i style="width:${100 * a / mx}%;background:var(--ink-2)"></i></span><span class="n">${a}</span>
      </div>
      ${drv.length ? `<div class="sect">Why this forecast · top drivers</div>
      <div class="drv">${drv.map(x => `<div class="row">
          <span>${x[0]}<br><span class="fv">${x[2] ?? ""}</span></span>
          <span class="track"><i style="${x[1] >= 0 ? "left:50%" : "right:50%"};width:${50 * Math.abs(x[1]) / dm}%;background:${x[1] >= 0 ? "var(--accent)" : "var(--div-neg)"}"></i></span>
          <span class="val">${x[1] >= 0 ? "+" : "−"}${Math.abs(x[1]).toFixed(1)}</span></div>`).join("")}</div>` : ""}
      <div class="sect">${YEARS[0]}–${YEARS[YEARS.length - 1]} · dwellings converted per year</div>
      <div class="ts"><svg viewBox="0 0 ${tsW} ${tsH}" role="img" aria-label="Forecast and actual conversions by year">
        ${ticks.map(t => `<line x1="${mL}" x2="${tsW - mR}" y1="${ys(t)}" y2="${ys(t)}" stroke="var(--line)"/><text class="ax" x="${mL - 4}" y="${ys(t) + 3}" text-anchor="end">${t}</text>`).join("")}
        ${YEARS.map(y => `<text class="ax" x="${xs(y)}" y="${tsH - 6}" text-anchor="middle">${String(y).slice(2)}</text>`).join("")}
        <line x1="${testX}" x2="${testX}" y1="${mT}" y2="${tsH - mB}" stroke="var(--ink-3)" stroke-dasharray="2 3"/>
        <text class="ax" x="${testX + 3}" y="${mT + 8}">test →</text>
        <path d="${line("actual")}" fill="none" stroke="var(--ink-2)" stroke-width="1.6" stroke-dasharray="4 3"/>
        <path d="${line("forecast")}" fill="none" stroke="var(--accent)" stroke-width="2"/>
        <circle cx="${xs(year)}" cy="${ys(p)}" r="3.5" fill="var(--accent)"/>
        <circle cx="${xs(year)}" cy="${ys(a)}" r="3" fill="var(--surface)" stroke="var(--ink-2)" stroke-width="1.6"/>
      </svg></div>
      <div class="lg"><span>Forecast</span><span class="a">Actual</span></div>`;
  }

  // ---------- scouting list ----------
  function renderList() {
    const n = +$("list-n").value;
    const rows = feats.slice().sort((a, b) => (+b.a.forecast[year] || 0) - (+a.a.forecast[year] || 0)).slice(0, n);
    const tb = document.querySelector("#list tbody");
    tb.innerHTML = rows.map((f, i) => {
      const top = drivers(f)[0];
      return `<tr data-code="${f.code}"><td>${i + 1}</td><td>${f.name}<br><span class="fv">${f.code}</span></td>
        <td class="num">${(+f.a.forecast[year] || 0).toFixed(0)}</td><td class="num">${+f.a.actual[year] || 0}</td>
        <td class="num">${+f.a.actual[year - 1] || 0}</td><td class="drvtag">${top ? top[0] : "—"}</td></tr>`;
    }).join("");
    tb.querySelectorAll("tr").forEach(tr => tr.onclick = () => { showTab("map"); const f = feats.find(x => x.code === tr.dataset.code); if (f) select(f); });
  }
  $("list-n").onchange = renderList;

  // ---------- tabs ----------
  function showTab(name) {
    document.querySelectorAll(".tabs button").forEach(b => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
    for (const t of ["map", "list", "method"]) $("tab-" + t).hidden = t !== name;
  }
  document.querySelectorAll(".tabs button").forEach(b => b.onclick = () => showTab(b.dataset.tab));

  paint();
  select(feats.slice().sort((a, b) => (+b.a.forecast[year] || 0) - (+a.a.forecast[year] || 0))[3]);
})();
