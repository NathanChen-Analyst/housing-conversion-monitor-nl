/* Housing Conversion Monitor NL — map page.
 * data/wijk_year_conversions.json  {meta:{years,suppress_below,national,...}, areas:{code:{name, n:{year:int|null}, suppressed:[years]}}}
 * data/wijken.geojson              one feature per wijk, properties.wijk_code (+ name)
 * data/provincies.geojson          optional province outlines (any properties)
 * data/outline.geojson, data/cities.json   backdrop and labels
 */
(async function () {
  const W = 900, H = 760;
  const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const $ = id => document.getElementById(id);
  const fmt = d3.format(",");
  const loadJSON = async url => { const r = await fetch(url); if (!r.ok) throw new Error(url); return r.json(); };

  const data = await loadJSON("data/wijk_year_conversions.json");
  const geo = await loadJSON("data/wijken.geojson");
  const provinces = await loadJSON("data/provincies.geojson").catch(() => null);
  const outline = await loadJSON("data/outline.geojson").catch(() => null);
  const cities = await loadJSON("data/cities.json").catch(() => []);

  // D3 reads lon/lat rings with spherical winding; GIS exports are usually the other way round.
  const ringArea = r => { let a = 0; for (let i = 0; i < r.length - 1; i++) a += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1]; return a; };
  const rewind = fc => { for (const f of fc.features) { const g = f.geometry; if (!g) continue;
    const polys = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
    for (const poly of polys) poly.forEach((ring, i) => { const a = ringArea(ring); if ((i === 0 && a > 0) || (i > 0 && a < 0)) ring.reverse(); }); } return fc; };
  rewind(geo); if (outline) rewind(outline); if (provinces) rewind(provinces);

  const YEARS = data.meta.years.map(Number), Y0 = YEARS[0], Y1 = YEARS[YEARS.length - 1];
  const SUP = data.meta.suppress_below || 3;
  $("unit-label").textContent = data.meta.unit || "wijk";

  // ---------- join ----------
  const feats = geo.features;
  for (const f of feats) {
    f.code = f.properties.wijk_code;
    const a = data.areas[f.code];
    const raw = (a && a.name) || f.properties.name || f.code;
    // CBS names many wijken "Wijk 01 Centrum (Stad)"; drop the number when a real name follows
    f.name = raw.replace(/^Wijk \d+ (?=[^(\s])/, "");
    f.n = {}; f.sup = new Set(a ? a.suppressed : []);
    for (const y of YEARS) f.n[y] = a ? a.n[y] : 0;
    f.total = YEARS.reduce((s, y) => s + (f.n[y] || 0), 0);
    f.hasData = !!a;
  }
  const cum = (f, y) => YEARS.filter(t => t <= y).reduce((s, t) => s + (f.n[t] || 0), 0);
  const visible = Object.fromEntries(YEARS.map(y => [y, feats.reduce((s, f) => s + (f.n[y] || 0), 0)]));
  const national = data.meta.national ? Object.fromEntries(YEARS.map(y => [y, +data.meta.national[y] || 0])) : visible;
  const nationalTotal = YEARS.reduce((s, y) => s + national[y], 0);
  const nWijken = feats.filter(f => f.hasData).length;
  const ranked = feats.filter(f => f.total > 0).sort((a, b) => b.total - a.total);
  const rankOf = new Map(ranked.map((f, i) => [f.code, i + 1]));

  // ---------- state & controls ----------
  const yearInput = $("year");
  yearInput.min = Y0; yearInput.max = Y1; yearInput.value = Y1;
  let year = Y1, mode = "cum", selected = null, timer = null;
  $("year-out").textContent = year;
  const val = f => mode === "year" ? (f.n[year] ?? 0) : cum(f, year);

  $("s-ev").textContent = fmt(nationalTotal);
  $("s-mae").textContent = fmt(nWijken);
  const peakY = YEARS.reduce((a, b) => national[a] >= national[b] ? a : b);
  $("s-cap").textContent = peakY;

  // ---------- projection & layers ----------
  const proj = d3.geoMercator().fitExtent([[24, 16], [W - 24, H - 16]], outline || geo);
  const path = d3.geoPath(proj);
  const svg = d3.select("#map"), g = svg.append("g");
  svg.append("defs").append("pattern").attr("id", "hatch").attr("patternUnits", "userSpaceOnUse").attr("width", 4).attr("height", 4)
    .attr("patternTransform", "rotate(45)").append("rect").attr("width", 1.2).attr("height", 4).attr("class", "hatch-bar");
  if (outline) g.selectAll("path.bg").data(outline.features).join("path")
    .attr("class", d => d.properties.kind === "water" ? "water" : "land").attr("d", path);
  const areaSel = g.append("g").selectAll("path").data(feats).join("path")
    .attr("class", "area").attr("d", path)
    .on("pointermove", (e, d) => showTip(e, d)).on("pointerleave", hideTip).on("click", (e, d) => select(d));
  if (provinces) g.append("g").selectAll("path").data(provinces.features).join("path").attr("class", "province").attr("d", path);
  const cityG = g.append("g").attr("pointer-events", "none");
  const big = cities.filter(c => c.w >= 0.2).map(c => ({ ...c, xy: proj([c.lon, c.lat]) }));
  cityG.selectAll("circle").data(big).join("circle").attr("class", "city").attr("cx", d => d.xy[0]).attr("cy", d => d.xy[1]).attr("r", 1.8);
  cityG.selectAll("text").data(big).join("text").attr("class", "city-label").attr("x", d => d.xy[0] + 4).attr("y", d => d.xy[1] + 3).text(d => d.name);

  const zoom = d3.zoom().scaleExtent([1, 16]).on("zoom", e => { g.attr("transform", e.transform);
    cityG.selectAll("text").style("font-size", (10 / Math.sqrt(e.transform.k)) + "px"); });
  svg.call(zoom);
  $("z-in").onclick = () => svg.transition().call(zoom.scaleBy, 1.6);
  $("z-out").onclick = () => svg.transition().call(zoom.scaleBy, 1 / 1.6);
  $("z-reset").onclick = () => svg.transition().call(zoom.transform, d3.zoomIdentity);

  // ---------- colour ----------
  const seq = () => d3.scaleLinear().domain([0, .2, .4, .6, .8, 1]).range([0, 1, 2, 3, 4, 5].map(i => css(`--seq-${i}`))).interpolate(d3.interpolateLab);
  function paint() {
    const vals = feats.map(val).filter(v => v > 0);
    const hi = Math.max(1, d3.quantile(vals.sort(d3.ascending), 0.97) || 1);
    const s = seq(), scale = v => s(Math.sqrt(Math.min(1, v / hi)));   // sqrt: lifts the many small values out of the floor
    areaSel.attr("fill", d => {
      if (mode === "year" && d.sup.has(year)) return "url(#hatch)";
      const v = val(d); return v > 0 ? scale(v) : "var(--land)";
    });
    $("lg-bar").style.background = `linear-gradient(90deg, ${d3.range(0, 1.001, 0.1).map(t => scale(t * t * hi)).join(",")})`;
    $("lg-title").textContent = mode === "year" ? `Dwellings converted in ${year}` : `Cumulative ${Y0}–${year}`;
    $("lg-min").textContent = "1"; $("lg-max").textContent = "≥" + fmt(Math.round(hi));
    $("s-total").textContent = fmt(national[year]); $("s-total-yr").textContent = year;
    document.querySelectorAll(".yr-txt").forEach(el => el.textContent = mode === "year" ? year : `${Y0}–${year}`);
    $("col-sel").textContent = mode === "year" ? `In ${year}` : `To ${year}`;
    if (selected) renderPanel(selected);
    renderList();
  }
  for (const [id, m] of [["m-pred", "year"], ["m-act", "cum"]]) {
    $(id).onclick = () => { mode = m; document.querySelectorAll(".seg button").forEach(b => b.setAttribute("aria-pressed", "false")); $(id).setAttribute("aria-pressed", "true"); paint(); };
  }
  const setYear = y => { year = y; yearInput.value = y; $("year-out").textContent = y; paint(); };
  yearInput.oninput = () => setYear(+yearInput.value);
  $("play").onclick = () => {
    if (timer) { clearInterval(timer); timer = null; $("play").textContent = "▶"; $("play").setAttribute("aria-pressed", "false"); return; }
    if (year >= Y1) setYear(Y0);
    $("play").textContent = "❚❚"; $("play").setAttribute("aria-pressed", "true");
    timer = setInterval(() => { if (year >= Y1) { $("play").onclick(); return; } setYear(year + 1); }, 800);
  };
  if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", paint);

  // ---------- tooltip ----------
  const tip = $("tip"), box = $("mapbox");
  const show = (f, y) => f.sup.has(y) ? `<${SUP}` : fmt(f.n[y] ?? 0);
  function showTip(e, d) {
    const r = box.getBoundingClientRect();
    tip.style.left = (e.clientX - r.left) + "px"; tip.style.top = (e.clientY - r.top) + "px";
    tip.innerHTML = `${d.name}<br>${year}: <b>${show(d, year)}</b> · ${Y0}–${Y1}: <b>${fmt(d.total)}${d.sup.size ? "+" : ""}</b>`;
    tip.style.opacity = 1;
  }
  function hideTip() { tip.style.opacity = 0; }

  // ---------- selected-neighbourhood card ----------
  function select(d) { selected = d; areaSel.classed("sel", f => f === d); renderPanel(d); renderList(); }

  function bars(getY, w = 420, h = 120, mark = year, compare = null) {
    const mL = 40, mR = 8, mT = 10, mB = 20;
    const xs = d3.scaleBand().domain(YEARS).range([mL, w - mR]).padding(0.25);
    const ymax = Math.max(1, d3.max(YEARS, getY));
    const ys = d3.scaleLinear().domain([0, ymax]).nice().range([h - mB, mT]);
    return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Dwellings converted per year">
      ${ys.ticks(3).map(t => `<line x1="${mL}" x2="${w - mR}" y1="${ys(t)}" y2="${ys(t)}" stroke="var(--line)"/><text class="ax" x="${mL - 5}" y="${ys(t) + 3}" text-anchor="end">${fmt(t)}</text>`).join("")}
      ${YEARS.map(y => `<rect x="${xs(y)}" y="${ys(getY(y))}" width="${xs.bandwidth()}" height="${ys(0) - ys(getY(y))}" rx="1.5" fill="${y === mark ? "var(--accent)" : "var(--seq-2)"}"/>`).join("")}
      ${compare ? `<path d="${d3.line().x(y => xs(y) + xs.bandwidth() / 2).y(y => ys(compare(y)))(YEARS)}" fill="none" stroke="var(--ink-2)" stroke-width="1.4" stroke-dasharray="3 3"/>` : ""}
      ${YEARS.map(y => `<text class="ax" x="${xs(y) + xs.bandwidth() / 2}" y="${h - 6}" text-anchor="middle">${String(y).slice(2)}</text>`).join("")}
    </svg>`;
  }

  function renderPanel(d) {
    const rank = rankOf.get(d.code), share = nationalTotal ? d.total / nationalTotal * 100 : 0;
    const peak = YEARS.reduce((a, b) => (d.n[a] || 0) >= (d.n[b] || 0) ? a : b);
    const scaleNat = d.total / nationalTotal;   // national series at this wijk's share: "if it had followed the country"
    $("panel").innerHTML = `
      <div class="top-row"><h2>${d.name}</h2><span class="sect">${rank ? `#${rank} of ${fmt(nWijken)}` : "no conversions"}</span></div>
      <div class="meta">
        <span><b>${fmt(d.total)}${d.sup.size ? "+" : ""}</b> dwellings ${Y0}–${Y1}</span>
        <span><b>${share.toFixed(1)}%</b> of national</span>
        <span><b>${show(d, year)}</b> in ${year}</span>
        ${d.total ? `<span>peak <b>${peak}</b></span>` : ""}
      </div>
      <div class="ts">${d.hasData ? bars(y => d.n[y] || 0, 420, 130, year, y => national[y] * scaleNat) : '<div class="empty">No conversions detected here.</div>'}</div>
      <div class="lg"><span>This neighbourhood</span><span class="a">National trend, scaled</span></div>
      ${d.sup.size ? `<div class="fv">Hatched years (${[...d.sup].sort().join(", ")}): fewer than ${SUP}, not shown exactly.</div>` : ""}`;
  }

  // ---------- ranking card ----------
  function renderList() {
    const n = +$("list-n").value;
    const rows = feats.filter(f => val(f) > 0).sort((a, b) => val(b) - val(a)).slice(0, n);
    const tb = document.querySelector("#list tbody");
    tb.innerHTML = rows.map((f, i) => `<tr data-code="${f.code}" class="${selected && selected.code === f.code ? "active" : ""}"><td>${i + 1}</td><td>${f.name}</td>
        <td class="num sel-col">${fmt(val(f))}</td><td class="num">${fmt(f.total)}</td><td class="num">${(f.total / nationalTotal * 100).toFixed(1)}%</td></tr>`).join("");
    tb.querySelectorAll("tr").forEach(tr => tr.onclick = () => { const f = feats.find(x => x.code === tr.dataset.code); if (f) select(f); });
  }
  $("list-n").onchange = renderList;

  paint();
  select(ranked[0]);
})();
