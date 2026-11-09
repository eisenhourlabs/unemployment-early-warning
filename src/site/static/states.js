/* Unemployment Watch: the States page's map, tiles, table and National / Weighted view.
   Data: assets/states.json (written by src/site/states.py): one array per measure and area, aligned with the
   lists of weeks and months. The map, tiles and table show the last week (or month) at or before the END of the
   page's time setting; site.js announces every change with a "uw:range" event and lends its theme colours.
   Wording rule: the page says "Weighted" and never shows weights, ranks of weights or a count of weighted states.
   The map and table are the same in both views. Counts of states meeting a condition sit in [data-count] elements.
   Plain JavaScript; plotly.js draws the map (the US outline is assets/usa_110m.json, so nothing is fetched
   from outside the site). */
(function () {
  "use strict";

  var P = null;                       // the data file
  var measureKey = "icy";             // the map's measure
  var sort = { key: "name", dir: 1 };
  var snap = null;                    // the snapshot shown (indexes into weeks / months)
  var mapEl = document.getElementById("states-map");
  var phone = window.matchMedia("(max-width: 759px)");
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var MINUS = "−";

  // Map colours. Change measures: blue (fewer claims) <-> orange (more claims) around a grey midpoint; levels: one
  // blue ramp. Red / amber / green are kept for the early-warning signal and are not used here.
  var SCALES = {
    light: { diverging: [[0, "#1c5cab"], [0.5, "#f0efec"], [1, "#c2501f"]],
             sequential: [[0, "#e3edf9"], [1, "#104281"]], missing: "#d9d8d3", border: "#fcfcfb" },
    dark:  { diverging: [[0, "#5598e7"], [0.5, "#383835"], [1, "#eb6834"]],
             sequential: [[0, "#22344a"], [1, "#9ec5f4"]], missing: "#3a3a36", border: "#1a1a19" }
  };

  // ---------------------------------------------------------------- formats (same as the Python side)
  function fmtDate(s) { var p = s.split("-"); return MONTHS[+p[1] - 1] + " " + (+p[2]) + ", " + p[0]; }
  function fmtMonth(s) { var p = s.split("-"); return MONTHS[+p[1] - 1] + " " + p[0]; }
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

  // ---------------------------------------------------------------- snapshot for an end date
  // Index of the last entry <= key in a sorted list (or -1).
  function lastAtOrBefore(list, key) {
    var lo = 0, hi = list.length - 1, ans = -1;
    while (lo <= hi) { var mid = (lo + hi) >> 1; if (list[mid] <= key) { ans = mid; lo = mid + 1; } else hi = mid - 1; }
    return ans;
  }
  // From index i back, the first period in which at least 90% of the areas that carry this measure report it.
  // (DOL's monthly state report and the weekly files arrive state by state: a period with only a few early
  // reporters would leave most of the map blank, so the page shows the last nearly complete period instead.)
  function lastWithData(arrays, i) {
    var carriers = arrays.filter(function (arr) { return arr.some(function (v) { return v !== null; }); }).length;
    var need = Math.ceil(0.9 * carriers);
    for (; i >= 0; i--) {
      var n = 0;
      for (var a = 0; a < arrays.length; a++) if (arrays[a][i] !== null) n++;
      if (n >= need) return i;
    }
    return -1;
  }
  function snapshot(end) {
    var wi = lastAtOrBefore(P.weeks, end), mi = lastAtOrBefore(P.months, end.slice(0, 7));
    return {
      ic: lastWithData(P.w.icy, wi),          // new claims week (needs a year-on-year value)
      cc: lastWithData(P.w.cc, wi),           // continuing claims week (a week behind)
      ur: lastWithData(P.m.ur, mi),
      gap: lastWithData(P.m.gap, mi),
      exh: lastWithData(P.m.exh, mi)
    };
  }
  // Value of a measure for area a in the current snapshot, and the date it belongs to.
  function value(key, a) {
    switch (key) {
      case "ic4": case "icy": return P.w[key][a][snap.ic];
      case "cc": case "ccy": return P.w[key][a][snap.cc];
      case "ur": return P.m.ur[a][snap.ur];
      case "gap": return P.m.gap[a][snap.gap];
      case "exh": case "dur": return P.m[key][a][snap.exh];
    }
    return null;
  }
  function periodOf(key) {
    if (key === "icy" || key === "ic4") return "Week ending " + fmtDate(P.weeks[snap.ic]);
    if (key === "cc" || key === "ccy") return "Week ending " + fmtDate(P.weeks[snap.cc]);
    return fmtMonth(P.months[snap[key === "dur" ? "exh" : key]]);
  }
  // Last week at or before the snapshot week in which area a reported initial claims (or -1).
  function reportedThrough(a) {
    for (var i = snap.ic; i >= 0; i--) if (P.w.ic[a][i] !== null) return i;
    return -1;
  }
  function weighted() { return document.documentElement.dataset.view === "weighted"; }

  // ---------------------------------------------------------------- tiles and the "as of" line
  function renderTiles() {
    var t = P.t, i = snap.ic, j = snap.cc;
    el("states-asof").textContent = "As of: claims through week ending " + fmtDate(P.weeks[i]) +
      " (continuing claims " + fmtDate(P.weeks[j]) + ") · state unemployment " + fmtMonth(P.months[snap.ur]);

    fill("tile-icy", "value", "National " + fmt(t.nat_icy[i], 1, "%", true));
    fill("tile-icy", "weighted", "Weighted " + fmt(t.w_icy[i], 1, "%", true));
    fill("tile-icy", "asof", "4 weeks to " + fmtDate(P.weeks[i]) + ", vs. the same weeks a year earlier");

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

  // ---------------------------------------------------------------- map
  function measure() { return P.measures.filter(function (m) { return m.key === measureKey; })[0]; }
  function quantile(sorted, q) {
    var pos = (sorted.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  }
  function drawMap() {
    var m = measure(), theme = window.UW.themeName(), sc = SCALES[theme], t = window.UW.themes[theme];
    var period = periodOf(m.key);
    var have = [], missing = [];
    P.areas.forEach(function (ar, a) {
      if (!ar.map) return;
      var v = value(m.key, a);
      (v === null ? missing : have).push({ code: ar.code, name: ar.name, v: v });
    });
    // rank among states with a value (1st = highest)
    var order = have.slice().sort(function (x, y) { return y.v - x.v; });
    order.forEach(function (h, k) { h.rank = k + 1; });
    var vals = have.map(function (h) { return h.v; }).sort(function (x, y) { return x - y; });
    var zmin, zmax;
    if (m.kind === "diverging") {
      var lim = Math.max(Math.abs(quantile(vals, 0.05)), Math.abs(quantile(vals, 0.95))) || 1;
      zmin = -lim; zmax = lim;
    } else {
      zmin = quantile(vals, 0.05); zmax = quantile(vals, 0.95);
      if (zmax <= zmin) zmax = zmin + 1;
    }
    var unit = m.unit.trim();
    var traces = [{
      type: "choropleth", locationmode: "USA-states",
      locations: have.map(function (h) { return h.code; }), z: have.map(function (h) { return h.v; }),
      zmin: zmin, zmax: zmax, colorscale: sc[m.kind], autocolorscale: false,
      marker: { line: { color: sc.border, width: 1 } },
      customdata: have.map(function (h) {
        return [h.name, fmt(h.v, m.decimals, m.unit, m.signed), ordinal(h.rank) + " highest of " + have.length, period];
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
      customdata: missing.map(function (h) { return [h.name, "not reported for " + period.toLowerCase().replace("week", "the week")]; }),
      hovertemplate: "<b>%{customdata[0]}</b><br>%{customdata[1]}<extra></extra>"
    });
    var layout = {
      geo: { scope: "usa", projection: { type: "albers usa" }, bgcolor: t.bg, showlakes: false, showland: true,
             landcolor: sc.missing, subunitcolor: sc.border, showframe: false },
      margin: { l: 0, r: 0, t: 0, b: phone.matches ? 40 : 0 }, height: phone.matches ? 300 : 460,
      paper_bgcolor: t.bg, font: { family: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", color: t.text },
      dragmode: false,
      hoverlabel: { bgcolor: t.hoverBg, bordercolor: t.axis, font: { color: t.hoverText } }
    };
    var note = el("map-missing");
    note.hidden = !missing.length;
    note.textContent = missing.length ? "Grey: not reported for " + period.toLowerCase().replace("week", "the week") +
      " (" + missing.map(function (h) { return h.code; }).join(", ") + ")." : "";
    el("map-footer").textContent = m.label + ", " + period.replace("Week", "week") + ". " + m.footer +
      " Sources: DOL ETA 539 / ETA 5159, BLS via FRED; our calculation.";
    return Plotly.react(mapEl, traces, layout, { displayModeBar: false, responsive: true, scrollZoom: false,
                                                 topojsonURL: "assets/" });
  }

  // ---------------------------------------------------------------- table
  var COLS = [
    { key: "ic4", dec: 0 }, { key: "icy", dec: 1, unit: "%", signed: true }, { key: "cc", dec: 2, unit: "%" },
    { key: "ccy", dec: 2, unit: " pt", signed: true }, { key: "ur", dec: 1, unit: "%" },
    { key: "gap", dec: 1, unit: " pt", signed: true }, { key: "exh", dec: 1, unit: "%" }, { key: "dur", dec: 1 }
  ];
  function renderTable() {
    var rows = P.areas.map(function (ar, a) {
      var r = { name: ar.name, code: ar.code, through: reportedThrough(a) };
      COLS.forEach(function (c) { r[c.key] = value(c.key, a); });
      return r;
    });
    rows.sort(function (x, y) {
      var u = x[sort.key], v = y[sort.key];
      var nu = u === null || u === undefined || u === -1, nv = v === null || v === undefined || v === -1;
      if (nu || nv) return nu && nv ? (x.name < y.name ? -1 : 1) : (nu ? 1 : -1);   // blanks always last
      if (u < v) return -sort.dir;
      if (u > v) return sort.dir;
      return x.name < y.name ? -1 : 1;
    });
    var body = document.querySelector("#state-table tbody");
    body.textContent = "";
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      var td = document.createElement("td");
      td.textContent = r.name;
      tr.appendChild(td);
      COLS.forEach(function (c) {
        var cell = document.createElement("td");
        cell.className = "num";
        cell.textContent = fmt(r[c.key], c.dec, c.unit, c.signed);
        tr.appendChild(cell);
      });
      var last = document.createElement("td");
      if (r.through === -1) last.textContent = "no data";
      else if (r.through < snap.ic) {
        last.textContent = "not reported for week ending " + fmtDate(P.weeks[snap.ic]) + " (latest " +
          fmtDate(P.weeks[r.through]) + ")";
        tr.className = "late";
      } else last.textContent = fmtDate(P.weeks[r.through]);
      tr.appendChild(last);
      body.appendChild(tr);
    });
    document.querySelectorAll("#state-table th").forEach(function (th) {
      var b = th.querySelector("button");
      th.setAttribute("aria-sort", b.dataset.sort === sort.key ? (sort.dir > 0 ? "ascending" : "descending") : "none");
    });
    el("table-asof").textContent = "New claims: 4 weeks to " + fmtDate(P.weeks[snap.ic]) + " · continuing claims: " +
      fmtDate(P.weeks[snap.cc]) + " · unemployment rate: " + fmtMonth(P.months[snap.ur]) +
      " · exhaustion and weeks paid: " + fmtMonth(P.months[snap.exh]) + ".";
  }
  document.querySelectorAll("#state-table th button").forEach(function (b) {
    b.addEventListener("click", function () {
      // first click: names A-Z, numbers highest first; a second click reverses
      if (sort.key === b.dataset.sort) sort.dir = -sort.dir;
      else sort = { key: b.dataset.sort, dir: b.dataset.sort === "name" ? 1 : -1 };
      renderTable();
    });
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
    renderTiles();
    renderTable();
    return drawMap();
  }
  document.querySelectorAll("input[name=measure]").forEach(function (r) {
    r.addEventListener("change", function () { if (r.checked) { measureKey = r.value; drawMap(); } });
  });
  document.addEventListener("uw:range", function (e) { if (P) update(e.detail.end); });
  document.addEventListener("uw:theme", function () { if (P) drawMap(); });
  phone.addEventListener("change", function () { if (P) drawMap(); });

  markView();
  var checked = document.querySelector("input[name=measure]:checked");   // a browser may restore a choice on reload
  if (checked) measureKey = checked.value;
  fetch("assets/states.json").then(function (r) {
    if (!r.ok) throw new Error("states.json: " + r.status);
    return r.json();
  }).then(function (data) {
    P = data;
    return update(window.UW.pageEnd());
  }).then(function () {
    document.body.dataset.statesReady = "true";
  }).catch(function (err) {
    el("states-asof").textContent = "State data could not be loaded.";
    console.error(err);
  });
})();
