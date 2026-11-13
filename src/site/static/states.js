/* Unemployment Watch: the States page's map, tiles, lists, table, drill-down and National / Weighted view.
   Data: assets/states.json (written by src/site/states.py): one array per measure and area, aligned with the lists of
   weeks, months and quarters. Everything follows the END of the page's time setting: site.js announces each change
   ("uw:range") and lends its theme colours (window.UW).
   Snapshot rule: a column / map measure shows the last period at or before the end in which at least 90% of the areas
   carrying that measure report; a state that has not reported that period shows its own latest value (up to a few
   periods back) WITH ITS OWN DATE, or "not reported" (review Gate 2).
   Wording rule: "Weighted" only; no weights, ranks of weights or a count of weighted states. Counts of states meeting a
   condition sit in [data-count] elements. Plain JavaScript; plotly.js draws the map and the drill-down charts. */
(function () {
  "use strict";

  var P = null;                       // the data file
  var measureKey = "icy";             // the map's measure
  var sort = { key: "name", dir: 1 };
  var snap = null;                    // indexes of the periods shown
  var drillCode = null;               // state shown in the drill-down
  var mapEl = document.getElementById("states-map");
  var phone = window.matchMedia("(max-width: 759px)");
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var MINUS = "−";
  var DAY = 86400000;

  // Map colours. Change measures: blue (fewer claims) <-> orange (more claims) around a grey midpoint; levels: one
  // blue ramp. Red / amber / green are kept for the early-warning signal and are not used here.
  var SCALES = {
    light: { diverging: [[0, "#1c5cab"], [0.5, "#f0efec"], [1, "#c2501f"]],
             sequential: [[0, "#e3edf9"], [1, "#104281"]], missing: "#d9d8d3", border: "#fcfcfb" },
    dark:  { diverging: [[0, "#5598e7"], [0.5, "#383835"], [1, "#eb6834"]],
             sequential: [[0, "#22344a"], [1, "#9ec5f4"]], missing: "#3a3a36", border: "#1a1a19" }
  };

  // Every value the page shows: where it lives and how it is formatted. group: w(eekly) / m(onthly) / q(uarterly);
  // at: which snapshot index it uses; back: how many periods back a late state's own latest value may come from.
  var COLS = {
    ic4: { group: "w", at: "ic", back: 8, dec: 0 },
    icy: { group: "w", at: "ic", back: 8, dec: 1, unit: "%", signed: true },
    icn: { group: "w", at: "ic", back: 8, dec: 0, unit: "%", signed: true },
    cc:  { group: "w", at: "cc", back: 8, dec: 2, unit: "%" },
    ccy: { group: "w", at: "cc", back: 8, dec: 2, unit: " pt", signed: true },
    ur:  { group: "m", at: "ur", back: 3, dec: 1, unit: "%" },
    gap: { group: "m", at: "gap", back: 3, dec: 1, unit: " pt", signed: true },
    exh: { group: "m", at: "exh", back: 3, dec: 1, unit: "%" },
    exhc: { group: "m", at: "exh", back: 3, dec: 1, unit: " pt", signed: true },
    dur: { group: "m", at: "exh", back: 3, dec: 1 },
    pot: { group: "q", at: "pot", back: 0, dec: 1 }     // ETA 218: a missing quarter reads "not reported" (review Gate 2)
  };
  var TABLE = ["ic4", "icy", "icn", "spark", "cc", "ccy", "ur", "gap", "exh", "exhc", "dur", "pot"];

  // ---------------------------------------------------------------- formats (same as the Python side)
  function fmtDate(s) { var p = s.split("-"); return MONTHS[+p[1] - 1] + " " + (+p[2]) + ", " + p[0]; }
  function fmtShort(s) { var p = s.split("-"); return MONTHS[+p[1] - 1] + " " + (+p[2]); }
  function fmtMonth(s) { var p = s.split("-"); return MONTHS[+p[1] - 1] + " " + p[0]; }
  function fmtQuarter(s) { var p = s.split("-"); return "Q" + Math.ceil(+p[1] / 3) + " " + p[0]; }
  function num(v, dec) {
    return Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  }
  function fmt(v, dec, unit, signed) {
    if (v === null || v === undefined) return "—";
    var r = +v.toFixed(dec);
    var sign = r < 0 ? MINUS : (signed && r > 0 ? "+" : "");
    return sign + num(r, dec) + (unit || "");
  }
  function ordinal(n) {
    var s = (n % 100 >= 11 && n % 100 <= 13) ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th");
    return n + s;
  }
  function el(id) { return document.getElementById(id); }
  function fill(tile, field, text) { var e = el(tile).querySelector("[data-fill=" + field + "]"); if (e) e.textContent = text; }
  function isoDays(s) { return Date.parse(s + "T00:00:00Z"); }
  function isoOf(ms) { return new Date(ms).toISOString().slice(0, 10); }

  // ---------------------------------------------------------------- periods and values
  function keys(group) { return group === "w" ? P.weeks : group === "m" ? P.months : P.quarters; }
  function arrays(key) { var c = COLS[key]; return P[c.group][key]; }
  function periodText(group, i) {
    var k = keys(group)[i];
    return group === "w" ? "Week ending " + fmtDate(k) : group === "m" ? fmtMonth(k) : fmtQuarter(k);
  }
  function shortPeriod(group, i) {
    var k = keys(group)[i];
    return group === "w" ? fmtShort(k) : group === "m" ? fmtMonth(k) : fmtQuarter(k);
  }
  function lastAtOrBefore(list, key) {
    var lo = 0, hi = list.length - 1, ans = -1;
    while (lo <= hi) { var mid = (lo + hi) >> 1; if (list[mid] <= key) { ans = mid; lo = mid + 1; } else hi = mid - 1; }
    return ans;
  }
  // From index i back, the first period in which at least 90% of the areas that carry this measure report it.
  function lastWithData(arrs, i) {
    var carriers = arrs.filter(function (arr) { return arr.some(function (v) { return v !== null; }); }).length;
    var need = Math.ceil(0.9 * carriers);
    for (; i >= 0; i--) {
      var n = 0;
      for (var a = 0; a < arrs.length; a++) if (arrs[a][i] !== null) n++;
      if (n >= need) return i;
    }
    return -1;
  }
  function snapshot(end) {
    var wi = lastAtOrBefore(P.weeks, end), mi = lastAtOrBefore(P.months, end.slice(0, 7));
    var qi = lastAtOrBefore(P.quarters, end);
    return { ic: lastWithData(P.w.icy, wi), cc: lastWithData(P.w.cc, wi), ur: lastWithData(P.m.ur, mi),
             gap: lastWithData(P.m.gap, mi), exh: lastWithData(P.m.exh, mi), pot: lastWithData(P.q.pot, qi) };
  }
  // A state's value for a column: at the column's period, or its own latest value a few periods back (with its own
  // index), or nothing. ever = whether the area has this measure at all ("not reported" vs "n/a").
  function cell(key, a) {
    var c = COLS[key], arr = arrays(key)[a], base = snap[c.at];
    for (var i = base; i >= 0 && i >= base - c.back; i--) if (arr[i] !== null) return { v: arr[i], i: i, base: base };
    return { v: null, i: -1, base: base, ever: arr.some(function (v) { return v !== null; }) };
  }
  function weighted() { return document.documentElement.dataset.view === "weighted"; }

  // ---------------------------------------------------------------- notes, tiles
  function renderNotes() {
    var i = snap.ic, wk = P.weeks[i];
    el("states-asof").textContent = "As of: claims through week ending " + fmtDate(wk) +
      " (continuing claims " + fmtDate(P.weeks[snap.cc]) + ") · state unemployment " + fmtMonth(P.months[snap.ur]);
    // Review Gate 2: the year-ago weeks of the comparison fall in (or just after) the 2025 shutdown
    var ago = isoDays(wk) - 364 * DAY, from = isoOf(ago - 21 * DAY), to = isoOf(ago);
    var hit = from <= P.shutdownWeeks[1] && to >= P.shutdownWeeks[0];
    var note = el("shutdown-note");
    note.hidden = !hit;
    note.textContent = hit ? "Read year-on-year changes with care: the year-ago weeks (" + fmtShort(from) + " – " +
      fmtDate(to) + ") fall in or just after the October–November 2025 federal shutdown, when DOL's weekly release " +
      "was suspended and claims processing was disrupted. \"vs. normal\" (the median of the 3 earlier years) is less " +
      "affected." : "";
  }
  function renderTiles() {
    var t = P.t, i = snap.ic, j = snap.cc;
    fill("tile-icy", "value", "National " + fmt(t.nat_icy[i], 1, "%", true));
    fill("tile-icy", "weighted", "Weighted " + fmt(t.w_icy[i], 1, "%", true));
    fill("tile-icy", "asof", "Claims per covered job, 4 weeks to " + fmtDate(P.weeks[i]) + ", vs. the same weeks a year earlier");
    fill("tile-cc", "value", "National " + fmt(t.nat_cc[j], 2, "%"));
    fill("tile-cc", "change", fmt(t.nat_ccy[j], 2, " pt", true) + " vs. a year ago");
    fill("tile-cc", "weighted", "Weighted " + fmt(t.w_cc[j], 2, "%") + " (" + fmt(t.w_ccy[j], 2, " pt", true) + ")");
    fill("tile-cc", "asof", "Per 100 covered jobs, 4 weeks to " + fmtDate(P.weeks[j]));
    var n = t.n_up[i];
    fill("tile-diff", "value", fmt(t.diff[i], 1, "%") + " of covered jobs");
    fill("tile-diff", "count", n === null ? "" : n + (n === 1 ? " state" : " states") + " (incl. DC)");
    fill("tile-diff", "weighted", "Weighted " + fmt(t.w_diff[i], 1, "%"));
    fill("tile-diff", "asof", "Week ending " + fmtDate(P.weeks[i]));
    var up = [];
    P.areas.forEach(function (ar, a) {
      var g = P.m.gap[a][snap.gap];
      if (ar.map && g !== null && g >= P.gapThreshold - 1e-9) up.push({ code: ar.code, g: g });
    });
    up.sort(function (x, y) { return y.g - x.g || (x.code < y.code ? -1 : 1); });
    fill("tile-gap", "value", up.length + (up.length === 1 ? " state" : " states"));
    fill("tile-gap", "list", up.length ? up.slice(0, 6).map(function (u) { return u.code + " " + fmt(u.g, 1, " pt", true); })
      .join(" · ") + (up.length > 6 ? " …" : "") : "None");
    fill("tile-gap", "asof", fmtMonth(P.months[snap.gap]) + " (BLS, seasonally adjusted)");
  }

  // ---------------------------------------------------------------- rising states and contributors
  function renderRising() {
    var list = el("rising-list"), i = snap.ic, items = [];
    list.textContent = "";
    P.areas.forEach(function (ar, a) {
      if (!ar.map) return;
      var why = [], n = P.w.icn[a];
      if (i >= 2 && [i, i - 1, i - 2].every(function (k) { return n[k] !== null && n[k] >= P.normalThreshold; }))
        why.push("new claims " + fmt(n[i], 0, "%", true) + " vs. normal (3+ weeks)");
      var g = P.m.gap[a][snap.gap];
      if (g !== null && g >= P.gapThreshold - 1e-9) why.push("unemployment " + fmt(g, 1, " pt", true) + " above its 12-month low");
      if (why.length) items.push({ a: a, name: ar.name, why: why.join("; ") });
    });
    if (!items.length) { var li = document.createElement("li"); li.textContent = "None at the end of this period."; list.appendChild(li); }
    items.forEach(function (it) {
      var li = document.createElement("li"), b = document.createElement("button");
      b.type = "button"; b.className = "linklike"; b.textContent = it.name; b.dataset.drill = P.areas[it.a].code;
      li.appendChild(b); li.appendChild(document.createTextNode(": " + it.why));
      list.appendChild(li);
    });
  }
  function renderContributors() {
    var i = snap.ic, body = el("contrib-body"), rows = [];
    body.textContent = "";
    P.areas.forEach(function (ar, a) { var v = P.w.wc[a][i]; if (v !== null) rows.push({ name: ar.name, v: v }); });
    var ups = rows.filter(function (r) { return r.v > 0; }).sort(function (x, y) { return y.v - x.v; }).slice(0, 5);
    var downs = rows.filter(function (r) { return r.v < 0; }).sort(function (x, y) { return x.v - y.v; }).slice(0, 5);
    el("contrib-why").textContent = "The weighted new-claims rate is " + fmt(P.t.w_icy[i], 1, "%", true) +
      " vs. a year ago (4 weeks to " + fmtDate(P.weeks[i]) + "). The states that add most to it, and that hold it down most:";
    for (var k = 0; k < Math.max(ups.length, downs.length, 1); k++) {
      var tr = document.createElement("tr");
      [ups[k], downs[k]].forEach(function (r) {
        var n = document.createElement("td"), v = document.createElement("td");
        n.textContent = r ? r.name : (k === 0 ? "none" : ""); v.className = "num"; v.textContent = r ? fmt(r.v, 1, "", true) : "";
        tr.appendChild(n); tr.appendChild(v);
      });
      body.appendChild(tr);
    }
  }

  // ---------------------------------------------------------------- map
  function measure() { return P.measures.filter(function (m) { return m.key === measureKey; })[0]; }
  function quantile(sorted, q) {
    var pos = (sorted.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  }
  function drawMap() {
    var m = measure(), c = COLS[m.key], theme = window.UW.themeName(), sc = SCALES[theme], t = window.UW.themes[theme];
    var have = [], missing = [];
    P.areas.forEach(function (ar, a) {
      if (!ar.map) return;
      var x = cell(m.key, a);
      (x.v === null ? missing : have).push({ code: ar.code, name: ar.name, v: x.v, i: x.i });
    });
    var order = have.slice().sort(function (x, y) { return y.v - x.v; });
    order.forEach(function (h, k) { h.rank = k + 1; });
    var vals = have.map(function (h) { return h.v; }).sort(function (x, y) { return x - y; });
    var zmin, zmax;
    if (m.zmin !== undefined && m.zmax !== undefined) {   // review WP9 C14: fixed for each measure
      zmin = m.zmin; zmax = m.zmax;
    } else if (m.kind === "diverging") {
      var lim = Math.max(Math.abs(quantile(vals, 0.05)), Math.abs(quantile(vals, 0.95))) || 1;
      zmin = -lim; zmax = lim;
    } else {
      zmin = quantile(vals, 0.05); zmax = quantile(vals, 0.95);
      if (zmax <= zmin) zmax = zmin + 1;
    }
    var unit = m.unit.trim(), period = periodText(c.group, snap[c.at]);
    var traces = [{
      type: "choropleth", locationmode: "USA-states",
      locations: have.map(function (h) { return h.code; }), z: have.map(function (h) { return h.v; }),
      zmin: zmin, zmax: zmax, colorscale: sc[m.kind], autocolorscale: false,
      marker: { line: { color: sc.border, width: 1 } },
      customdata: have.map(function (h) {
        return [h.name, fmt(h.v, m.decimals, m.unit, m.signed), ordinal(h.rank) + " highest of " + have.length,
                periodText(c.group, h.i)];
      }),
      hovertemplate: "<b>%{customdata[0]}</b><br>%{customdata[1]}<br>%{customdata[2]}<br>%{customdata[3]}<extra></extra>",
      colorbar: phone.matches
        ? { orientation: "h", thickness: 10, len: 0.9, x: 0.5, xanchor: "center", y: -0.02, yanchor: "top",
            ticksuffix: unit === "pt" ? "" : unit, outlinewidth: 0, tickfont: { color: t.text, size: 11 } }
        : { thickness: 12, len: 0.75, ticksuffix: unit === "pt" ? " pt" : unit, outlinewidth: 0,
            tickfont: { color: t.text, size: 11 } }
    }];
    if (missing.length) traces.push({
      type: "choropleth", locationmode: "USA-states", showscale: false,
      locations: missing.map(function (h) { return h.code; }), z: missing.map(function () { return 0; }),
      colorscale: [[0, sc.missing], [1, sc.missing]], marker: { line: { color: sc.border, width: 1 } },
      customdata: missing.map(function (h) { return [h.name, "not reported for " + period.toLowerCase()]; }),
      hovertemplate: "<b>%{customdata[0]}</b><br>%{customdata[1]}<extra></extra>"
    });
    // Review WP9 C14: states whose latest value is older than the period shown carry a dot (not only the tooltip)
    var older = have.filter(function (h) { return h.i < snap[c.at]; });
    if (older.length) traces.push({
      type: "scattergeo", locationmode: "USA-states", mode: "markers", name: "Older reading", showlegend: false,
      locations: older.map(function (h) { return h.code; }),
      marker: { size: 7, color: t.text, line: { color: t.bg, width: 1.5 } },
      customdata: older.map(function (h) { return [h.name, "latest value from " + periodText(c.group, h.i).toLowerCase()]; }),
      hovertemplate: "<b>%{customdata[0]}</b><br>%{customdata[1]}<extra></extra>"
    });
    var layout = {
      geo: { scope: "usa", projection: { type: "albers usa" }, bgcolor: t.bg, showlakes: false, showland: true,
             landcolor: sc.missing, subunitcolor: sc.border, showframe: false },
      margin: { l: 0, r: 0, t: 0, b: phone.matches ? 40 : 0 }, height: phone.matches ? 300 : 460,
      paper_bgcolor: t.bg, font: { family: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", color: t.text },
      dragmode: false, hoverlabel: { bgcolor: t.hoverBg, bordercolor: t.axis, font: { color: t.hoverText } }
    };
    var note = el("map-missing"), parts = [];
    if (missing.length) parts.push("Grey: not reported for " + period.toLowerCase() + " (" +
      missing.map(function (h) { return h.code; }).join(", ") + ").");
    if (older.length) parts.push("Dot: latest value is from an earlier period (" +
      older.map(function (h) { return h.code; }).join(", ") + ").");
    note.hidden = !parts.length;
    note.textContent = parts.join(" ");
    el("map-footer").textContent = m.label + ", " + period.replace("Week", "week") + ". " + m.footer +
      " A state that has not reported this period shows its own latest value, marked with a dot (its date is in the" +
      " tooltip). Colours use one fixed scale for each measure (" + fmt(zmin, m.decimals, m.unit, m.signed) + " to " +
      fmt(zmax, m.decimals, m.unit, m.signed) + ": the 5th to 95th percentile of all states' values, leaving out" +
      " March 2020 to December 2021), so a colour means the same at every date." +
      " Sources: DOL ETA 539 / ETA 5159, BLS via FRED; our calculation.";
    return Plotly.react(mapEl, traces, layout, { displayModeBar: false, responsive: true, scrollZoom: false,
                                                 topojsonURL: "assets/" }).then(function (gd) {
      if (!gd._uwClick) {
        gd._uwClick = true;
        gd.on("plotly_click", function (ev) { var p = ev.points && ev.points[0]; if (p && p.location) openDrill(p.location, true); });
      }
    });
  }

  // ---------------------------------------------------------------- table
  function sparkline(a) {
    var i = snap.ic, now = [], prev = [], arr = P.w.ic4[a];
    for (var k = i - 25; k <= i; k++) { now.push(k >= 0 ? arr[k] : null); prev.push(k - 52 >= 0 ? arr[k - 52] : null); }
    var vals = now.concat(prev).filter(function (v) { return v !== null; });
    if (vals.length < 4) return null;
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), W = 90, H = 22;
    function path(series) {
      var pts = [];
      series.forEach(function (v, k) {
        if (v === null) return;
        pts.push((k * (W - 2) / 25 + 1).toFixed(1) + "," + (H - 2 - (v - lo) / ((hi - lo) || 1) * (H - 4)).toFixed(1));
      });
      return pts.join(" ");
    }
    var ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H); svg.setAttribute("width", W); svg.setAttribute("height", H);
    svg.setAttribute("class", "spark"); svg.setAttribute("role", "img");
    var lastNow = now[now.length - 1], lastPrev = prev[prev.length - 1];
    svg.setAttribute("aria-label", "New claims, last 26 weeks: " + fmt(lastNow, 0) + " now vs. " + fmt(lastPrev, 0) + " a year earlier");
    [["spark-prev", prev], ["spark-now", now]].forEach(function (s) {
      var pl = document.createElementNS(ns, "polyline");
      pl.setAttribute("points", path(s[1])); pl.setAttribute("class", s[0]); svg.appendChild(pl);
    });
    return svg;
  }
  function renderTable() {
    var rows = P.areas.map(function (ar, a) {
      var r = { name: ar.name, code: ar.code, a: a, cells: {} };
      TABLE.forEach(function (k) { if (k !== "spark") { r.cells[k] = cell(k, a); r[k] = r.cells[k].v; } });
      return r;
    });
    rows.sort(function (x, y) {
      var u = x[sort.key], v = y[sort.key];
      var nu = u === null || u === undefined, nv = v === null || v === undefined;
      if (nu || nv) return nu && nv ? (x.name < y.name ? -1 : 1) : (nu ? 1 : -1);   // blanks always last
      if (u < v) return -sort.dir;
      if (u > v) return sort.dir;
      return x.name < y.name ? -1 : 1;
    });
    var body = document.querySelector("#state-table tbody");
    body.textContent = "";
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.dataset.drill = r.code;
      var td = document.createElement("td");
      td.textContent = r.name;
      tr.appendChild(td);
      TABLE.forEach(function (k) {
        var c = document.createElement("td");
        if (k === "spark") { var s = sparkline(r.a); if (s) c.appendChild(s); tr.appendChild(c); return; }
        var x = r.cells[k], col = COLS[k];
        c.className = "num";
        if (x.v === null) {
          c.textContent = x.ever ? "not reported" : "n/a";
          c.classList.add("muted");
          if (x.ever) tr.classList.add("late");
        } else {
          c.textContent = fmt(x.v, col.dec, col.unit, col.signed);
          if (x.i < x.base) {          // an earlier period than the column's: show its own date
            var d = document.createElement("span");
            d.className = "cell-date"; d.textContent = " (" + shortPeriod(col.group, x.i) + ")";
            c.appendChild(d);
            tr.classList.add("late");
          }
        }
        tr.appendChild(c);
      });
      body.appendChild(tr);
    });
    document.querySelectorAll("#state-table th").forEach(function (th) {
      var b = th.querySelector("button");
      if (!b) return;
      th.setAttribute("aria-sort", b.dataset.sort === sort.key ? (sort.dir > 0 ? "ascending" : "descending") : "none");
    });
    el("table-asof").textContent = "New claims: 4 weeks to " + fmtDate(P.weeks[snap.ic]) + " · continuing claims: " +
      fmtDate(P.weeks[snap.cc]) + " · unemployment: " + fmtMonth(P.months[snap.ur]) + " · exhaustion and weeks paid: " +
      fmtMonth(P.months[snap.exh]) + " · potential weeks: " + fmtQuarter(P.quarters[snap.pot]) +
      ". A value from an earlier period shows its own date.";
  }
  document.querySelectorAll("#state-table th button").forEach(function (b) {
    b.addEventListener("click", function () {
      // first click: names A-Z, numbers highest first; a second click reverses
      if (sort.key === b.dataset.sort) sort.dir = -sort.dir;
      else sort = { key: b.dataset.sort, dir: b.dataset.sort === "name" ? 1 : -1 };
      renderTable();
    });
  });

  // ---------------------------------------------------------------- drill-down
  function drillLayout(t, yTitle, xFmt) {
    return { height: 220, margin: { l: 48, r: 10, t: 6, b: 30 }, paper_bgcolor: t.bg, plot_bgcolor: t.bg,
             font: { family: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", size: 11, color: t.text },
             showlegend: true, legend: { orientation: "h", y: 1.12, x: 0, font: { size: 10 } },
             xaxis: { type: "date", tickformat: xFmt, linecolor: t.axis, showgrid: false, fixedrange: true },
             yaxis: { title: { text: yTitle, font: { size: 10 } }, gridcolor: t.grid, fixedrange: true, zeroline: false },
             hovermode: "x unified", dragmode: false,
             hoverlabel: { bgcolor: t.hoverBg, bordercolor: t.axis, font: { color: t.hoverText } } };
  }
  function series(group, arr, from, to) {
    var ks = keys(group), x = [], y = [];
    for (var k = 0; k < ks.length; k++) {
      var d = group === "m" ? ks[k] + "-01" : ks[k];
      if (d >= from && d <= to) { x.push(d); y.push(arr[k]); }
    }
    return { x: x, y: y };
  }
  function openDrill(code, scroll) {
    var a = P.areas.map(function (ar) { return ar.code; }).indexOf(code);
    if (a < 0) return;
    drillCode = code;
    el("drill-state").value = code;
    drawDrill();
    if (scroll) el("drill").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  // Review WP9 C14: the same measure, baseline and weeks that put a state on the watch list (renderRising)
  function flagLine(a) {
    var i = snap.ic, n = P.w.icn[a], thr = P.normalThreshold, run = 0, parts = [];
    for (var k = i; k >= 0 && n[k] !== null && n[k] >= thr; k--) run++;
    if (i >= 0 && n[i] !== null) {
      parts.push("New claims " + fmt(n[i], 0, "%", true) + " vs. normal for these weeks (4-week average claims rate, " +
        "week ending " + fmtDate(P.weeks[i]) + ", against the median of the same weeks in the 3 earlier years)" +
        (run ? ", " + run + (run === 1 ? " week" : " weeks") + " running at " + thr + "% or more" : "") + ".");
    }
    var g = P.m.gap[a][snap.gap];
    if (g !== null && g !== undefined) parts.push("Unemployment (3-month average) " + fmt(g, 1, " pt", true) +
      " vs. its 12-month low, " + fmtMonth(P.months[snap.gap]) + ".");
    var on = run >= 3 || (g !== null && g !== undefined && g >= P.gapThreshold - 1e-9);
    parts.push((on ? "On the watch list" : "Not on the watch list") + " (rule: new claims " + thr + "% or more above " +
      "normal for 3 weeks in a row, or unemployment " + P.gapThreshold + " point or more above its 12-month low).");
    return parts.join(" ");
  }
  function drawDrill() {
    if (!P || !drillCode) return;
    var a = P.areas.map(function (ar) { return ar.code; }).indexOf(drillCode);
    var t = window.UW.themes[window.UW.themeName()], end = window.UW.pageEnd();
    var from = isoOf(isoDays(end) - 5 * 365.25 * DAY);
    var cfg = { displayModeBar: false, responsive: true, staticPlot: false };
    // (a) new claims by week of year: the end year and the 3 before it (all drawn on one calendar year)
    var endYear = +end.slice(0, 4), ic = [];
    for (var yr = endYear - 3; yr <= endYear; yr++) {
      var s = series("w", P.w.ic[a], yr + "-01-01", yr === endYear ? end : yr + "-12-31");
      var cur = yr === endYear;
      ic.push({ x: s.x.map(function (d) { return "2000" + d.slice(4); }), y: s.y, mode: "lines", name: String(yr),
                line: { color: cur ? t.accent : t.greys[Math.min(endYear - yr - 1, 2)], width: cur ? 2.2 : 1.3 },
                hovertemplate: "%{y:,.0f}<extra>" + yr + "</extra>" });
    }
    Plotly.react("drill-ic", ic, drillLayout(t, "Claims", "%b"), cfg);
    var cc = series("w", P.w.cc[a], from, end);
    Plotly.react("drill-cc", [{ x: cc.x, y: cc.y, mode: "lines", name: "Rate", line: { color: t.accent, width: 2 },
                               hovertemplate: "%{y:.2f}%<extra></extra>" }],
                 Object.assign(drillLayout(t, "% of covered jobs", "%Y"), { showlegend: false }), cfg);
    var ur = series("m", P.m.ur[a], from, end), ur3 = series("m", P.m.ur3[a], from, end), low = series("m", P.m.urlow[a], from, end);
    Plotly.react("drill-ur", [
      { x: ur.x, y: ur.y, mode: "lines", name: "Monthly", line: { color: t.greys[1], width: 1 }, hovertemplate: "%{y:.1f}%<extra>Monthly</extra>" },
      { x: ur3.x, y: ur3.y, mode: "lines", name: "3-month average", line: { color: t.accent, width: 2 }, hovertemplate: "%{y:.2f}%<extra>3-mo avg</extra>" },
      { x: low.x, y: low.y, mode: "lines", name: "12-month low", line: { color: t.greys[0], width: 1.3, dash: "dot" }, hovertemplate: "%{y:.2f}%<extra>12-mo low</extra>" }
    ], drillLayout(t, "Percent", "%Y"), cfg);
    var ex = series("m", P.m.exh[a], from, end), du = series("m", P.m.dur[a], from, end);
    Plotly.react("drill-exh", [{ x: ex.x, y: ex.y, mode: "lines", name: "Exhaustion rate", line: { color: t.accent, width: 2 },
                                 hovertemplate: "%{y:.1f}%<extra></extra>" }],
                 Object.assign(drillLayout(t, "% of claimants", "%Y"), { showlegend: false }), cfg);
    Plotly.react("drill-dur", [{ x: du.x, y: du.y, mode: "lines", name: "Average weeks paid", line: { color: t.accent, width: 2 },
                                 hovertemplate: "%{y:.1f} weeks<extra></extra>" }],
                 Object.assign(drillLayout(t, "Weeks", "%Y"), { showlegend: false }), cfg);
    el("drill-title").textContent = "State detail: " + P.areas[a].name;
    el("drill-flag").textContent = flagLine(a);
  }
  el("drill-state").addEventListener("change", function (e) { openDrill(e.target.value, false); });
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-drill]");
    if (b && !e.target.closest("th")) openDrill(b.dataset.drill, true);
  });

  // ---------------------------------------------------------------- National / Weighted view
  function markView() {
    var w = weighted();
    document.querySelectorAll("[data-view]").forEach(function (b) {
      b.setAttribute("aria-pressed", String((b.dataset.view === "weighted") === w));
    });
    document.querySelectorAll("[data-view-only]").forEach(function (e) { e.hidden = (e.dataset.viewOnly === "weighted") !== w; });
  }
  document.querySelectorAll("[data-view]").forEach(function (b) {
    b.addEventListener("click", function () {
      if (b.dataset.view === "weighted") document.documentElement.dataset.view = "weighted";
      else delete document.documentElement.dataset.view;
      var p = new URLSearchParams(window.location.search);
      if (weighted()) p.set("view", "weighted"); else p.delete("view");
      history.replaceState(null, "", window.location.pathname + "?" + p.toString() + window.location.hash);
      markView();
      // charts drawn while their section was hidden need their real width
      document.querySelectorAll(".weighted-section .chart").forEach(function (gd) { if (gd.data) Plotly.Plots.resize(gd); });
      window.UW.redraw();
    });
  });

  // ---------------------------------------------------------------- wiring
  function update(end) {
    snap = snapshot(end);
    if (snap.ic < 0) { el("states-asof").textContent = "No state claims data before " + fmtDate(P.weeks[0]) + "."; return Promise.resolve(); }
    renderNotes(); renderTiles(); renderRising(); renderContributors(); renderTable(); drawDrill();
    return drawMap();
  }
  document.querySelectorAll("input[name=measure]").forEach(function (r) {
    r.addEventListener("change", function () { if (r.checked) { measureKey = r.value; drawMap(); } });
  });
  document.addEventListener("uw:range", function (e) { if (P) update(e.detail.end); });
  document.addEventListener("uw:theme", function () { if (P) { drawMap(); drawDrill(); } });
  phone.addEventListener("change", function () { if (P) drawMap(); });

  markView();
  var checked = document.querySelector("input[name=measure]:checked");   // a browser may restore a choice on reload
  if (checked) measureKey = checked.value;
  fetch("assets/states.json").then(function (r) {
    if (!r.ok) throw new Error("states.json: " + r.status);
    return r.json();
  }).then(function (data) {
    P = data;
    var sel = el("drill-state");
    P.areas.forEach(function (ar) { var o = document.createElement("option"); o.value = ar.code; o.textContent = ar.name; sel.appendChild(o); });
    drillCode = "CA";                           // a start: the state with the most covered jobs
    sel.value = drillCode;
    return update(window.UW.pageEnd());
  }).then(function () {
    document.body.dataset.statesReady = "true";
  }).catch(function (err) {
    el("states-asof").textContent = "State data could not be loaded.";
    console.error(err);
  });
})();
