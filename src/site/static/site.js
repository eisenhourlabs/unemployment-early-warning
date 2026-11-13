/* Unemployment Watch: browser-side behavior.
   build_site.py writes the chart data into the page; this script draws the charts with plotly.js and runs:
     - the page time control (every chart at once, y-axes rescaled to the visible window, range kept in the URL)
     - dark mode
     - Download CSV (visible range or full history) and Download image
   Plain JavaScript, no other libraries. */
(function () {
  "use strict";

  var data = JSON.parse(document.getElementById("page-data").textContent);
  var charts = data.charts.map(function (c) {
    // fixed: [from, to] for a chart that ignores the time control; zero: y-axis always includes 0
    // ahead: last date a forecast reaches (Phase 3); whatifAhead: last date of the what-if paths
    return { id: c.id, title: c.title, figure: c.figure, table: c.table, fixed: c.fixed, zero: c.zero,
             ahead: c.ahead, whatifAhead: c.whatif_ahead, whatif: false,
             el: document.getElementById("chart-" + c.id) };
  });
  var phone = window.matchMedia("(max-width: 759px)");
  var current = { key: data.defaultRange, from: null, to: null };   // the page's time setting

  // ---------------------------------------------------------------- colors per theme (same tokens as style.css)
  var THEMES = {
    light: { accent: "#2a78d6", faint: "rgba(42,120,214,0.35)", rgb: "42,120,214", bg: "#fcfcfb", text: "#52514e",
             greys: ["#6d6c67", "#93928c", "#b9b8b2"],
             grid: "#e8e7e3", axis: "#c8c7c2", recession: "rgba(120,120,120,0.16)", hoverBg: "#ffffff", hoverText: "#0b0b0b",
             // Phase 3: the risk signal (colour strip) and the event shading on the score history
             sig: { green: "#1f7a3a", amber: "#b76e00", red: "#c0392b" },
             events: { recession: "rgba(42,120,214,0.13)", scare: "rgba(214,120,42,0.16)" } },
    dark:  { accent: "#3987e5", faint: "rgba(57,135,229,0.40)", rgb: "57,135,229", bg: "#1a1a19", text: "#c3c2b7",
             greys: ["#b5b4ad", "#8a8983", "#62615c"],
             grid: "#2c2c29", axis: "#4a4a45", recession: "rgba(200,200,200,0.10)", hoverBg: "#262624", hoverText: "#f0efec",
             sig: { green: "#4cb46a", amber: "#e8a33d", red: "#ef6b5e" },
             events: { recession: "rgba(90,160,240,0.18)", scare: "rgba(240,160,90,0.18)" } }
  };
  function themeName() { return document.documentElement.dataset.theme === "dark" ? "dark" : "light"; }
  // States page: the National / Weighted view (kept in the address as ?view=weighted). A line with meta.view is
  // shown only while the page is in that view (states.js switches the view and asks for a redraw).
  function viewName() { return document.documentElement.dataset.view === "weighted" ? "weighted" : "national"; }

  // Return a copy of a chart's figure with the current theme's colors applied.
  function themed(fig) {
    var t = THEMES[themeName()];
    var f = JSON.parse(JSON.stringify(fig));
    f.data.forEach(function (tr) {
      var role = (tr.meta && tr.meta.role) || "";
      if (tr.meta && tr.meta.view) tr.visible = viewName() === tr.meta.view;
      var color = role.indexOf("faint") === 0 ? t.faint
                : role.indexOf("grey") === 0 ? t.greys[+role.slice(4)] : t.accent;
      if (tr.line && role !== "fan-edge" && role !== "fan") tr.line.color = color;
      if (tr.marker) tr.marker.color = color;
      if (tr.error_y) tr.error_y.color = color;
      if (role === "fan") tr.fillcolor = "rgba(" + t.rgb + "," + tr.meta.alpha + ")";
      if (role === "label") tr.textfont = Object.assign({}, tr.textfont, { color: t.text });
      if (tr.fillpattern) tr.fillpattern = Object.assign({}, tr.fillpattern, { fgcolor: t.greys[1] });
    });
    var L = f.layout;
    L.paper_bgcolor = t.bg; L.plot_bgcolor = t.bg;
    L.font = Object.assign({}, L.font, { color: t.text });
    L.xaxis = Object.assign({}, L.xaxis, { linecolor: t.axis, tickcolor: t.axis });
    L.yaxis = Object.assign({}, L.yaxis, { gridcolor: t.grid });
    L.hoverlabel = { bgcolor: t.hoverBg, bordercolor: t.axis, font: { color: t.hoverText } };
    (L.shapes || []).forEach(function (s) {
      var name = s.name || "";
      if (s.type === "line") s.line = Object.assign({}, s.line, { color: t.axis });   // zero lines
      else if (name.indexOf("sig-") === 0) s.fillcolor = t.sig[name.slice(4)];         // colour strip (risk signal)
      else if (name.indexOf("event-") === 0) s.fillcolor = t.events[name.slice(6)];    // event shading
      else s.fillcolor = t.recession;                                                 // recession bands
    });
    (L.annotations || []).forEach(function (a) { a.font = Object.assign({}, a.font, { color: t.text }); });
    // Phones: no drag-to-zoom (it would block scrolling the page); tap still shows values.
    L.dragmode = phone.matches ? false : "zoom";
    if (phone.matches) {
      // Narrower margins on phones, but keep room for end-of-line labels (charts with a wide right margin)
      L.margin = Object.assign({}, L.margin, { l: 44, r: L.margin && L.margin.r > 16 ? L.margin.r : 8 });
      if (L.xaxis.dtick === "M1") L.xaxis.dtick = "M2";   // every other month, so labels stay level
    }
    delete L.template;
    return f;
  }

  // ---------------------------------------------------------------- time windows
  function iso(d) { return d.toISOString().slice(0, 10); }
  function yearsBefore(dateStr, n) {
    var d = new Date(dateStr + "T00:00:00Z");
    d.setUTCFullYear(d.getUTCFullYear() - n);
    return iso(d);
  }
  function firstDate(chart) {
    var first = null;
    chart.figure.data.forEach(function (tr) { if (tr.x && tr.x.length && (!first || tr.x[0] < first)) first = tr.x[0]; });
    return first;
  }
  // The [from, to] window for one chart under the page setting.
  function baseWindow(chart) {
    if (chart.fixed) return chart.fixed;      // e.g. the seasonal chart: always Jan to Dec
    var k = current.key, today = data.today;
    var years = { "1y": 1, "2y": 2, "5y": 5, "10y": 10, "20y": 20 }[k];
    if (years) return [yearsBefore(today, years), today];
    if (k === "max") return [firstDate(chart), today];
    if (k === "custom") return [current.from, current.to];
    var view = data.recessionViews.filter(function (v) { return v.key === k; })[0];
    return view ? [view.start, view.end] : [yearsBefore(today, 5), today];
  }
  // "Today's view" = the window reaches today. Only then are forecast elements (fans, nowcast, FOMC marker,
  // what-if paths) shown, and the x-axis runs on to where the forecast (or the what-if paths) end.
  function showsToday(w) { return w[1] >= data.today; }
  function windowFor(chart) {
    var w = baseWindow(chart);
    if (chart.fixed || !(chart.ahead || chart.whatifAhead) || !showsToday(w)) return w;
    // a chart with what-if paths but no fan (initial claims) only reaches past today while they are shown
    var end = chart.whatif && chart.whatifAhead > (chart.ahead || "") ? chart.whatifAhead : (chart.ahead || w[1]);
    return [w[0], end > w[1] ? end : w[1]];
  }
  // Which traces are visible in a window: forecast elements (meta.today) only in today's view; what-if paths
  // (meta.whatif) only while the toggle is on. A line the reader hid by clicking the legend stays hidden.
  function visibility(chart, w) {
    var today = showsToday(w);
    return chart.el.data.map(function (tr) {
      var m = tr.meta || {};
      if (m.whatif) return today && chart.whatif;
      if (m.today) return today ? (tr.visible === "legendonly" ? "legendonly" : true) : false;
      return tr.visible === undefined ? true : tr.visible;
    });
  }

  // Lowest and highest value of the visible lines between two dates, with a little padding.
  // vis: the visibility each trace is about to get (defaults to its current one).
  function yRange(gd, x0, x1, zero, vis) {
    var lo = Infinity, hi = -Infinity;
    gd.data.forEach(function (tr, ti) {
      var v = vis ? vis[ti] : tr.visible;
      if (v === false || v === "legendonly" || !tr.y || (tr.meta && tr.meta.noscale)) return;
      for (var i = 0; i < tr.x.length; i++) {
        var x = String(tr.x[i]).slice(0, 10), y = tr.y[i];
        var always = tr.meta && tr.meta.ref;   // reference lines (pre-recession averages) always stay in view
        if (y === null || y === undefined || (!always && (x < x0 || x > x1))) continue;
        if (y < lo) lo = y;
        if (y > hi) hi = y;
      }
    });
    if (lo === Infinity) return null;
    if (zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }   // bars and % changes keep the zero line in view
    var pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.1 || 1;
    return [lo - pad, hi + pad];
  }

  // Labels for the dotted reference lines (layout.meta.refs), placed for the y-axis range shown. Labels whose
  // lines would sit closer than about one line of text on screen are merged into one label, so they never overlap.
  function refLabels(gd, y) {
    var refs = gd.layout.meta && gd.layout.meta.refs;
    var others = (gd.layout.annotations || []).filter(function (a) { return a.name !== "ref"; });
    var hidden = gd.data.some(function (tr) { return tr.meta && tr.meta.ref && tr.visible === "legendonly"; });
    if (!refs || !y || hidden) return others;
    var h = (gd._fullLayout && gd._fullLayout._size && gd._fullLayout._size.h) || 250;
    var px = function (v) { return (v - y[0]) / (y[1] - y[0]) * h; };
    var groups = [];
    refs.slice().sort(function (a, b) { return a.value - b.value; }).forEach(function (r) {
      var g = groups[groups.length - 1];
      if (g && px(r.value) - px(g[g.length - 1].value) < 14) g.push(r); else groups.push([r]);
    });
    var color = THEMES[themeName()].text;
    return others.concat(groups.map(function (g) {
      return { name: "ref", xref: "paper", x: 1, xanchor: "right", y: g[g.length - 1].value, yanchor: "bottom",
               showarrow: false, text: g.map(function (r) { return r.text; }).join(" · "), font: { size: 10, color: color } };
    }));
  }

  var busy = false;   // true while this script changes a chart, so our own changes don't trigger the listeners
  function hasTodayTraces(chart) {
    return chart.el.data.some(function (tr) { return tr.meta && (tr.meta.today || tr.meta.whatif); });
  }
  function setView(chart, x0, x1) {
    var gd = chart.el;
    var vis = hasTodayTraces(chart) ? visibility(chart, [x0, x1]) : null;
    var y = yRange(gd, x0, x1, chart.zero, vis);
    var update = { "xaxis.range": [x0, x1] };
    if (y) update["yaxis.range"] = y; else update["yaxis.autorange"] = true;
    if (gd.layout.meta && gd.layout.meta.refs) update.annotations = refLabels(gd, y);
    busy = true;
    var done = function () { busy = false; };
    return (vis ? Plotly.update(gd, { visible: vis }, update) : Plotly.relayout(gd, update)).then(done, done);
  }
  // The end of the page's time setting: the date the States page's map, tiles and table show.
  function pageEnd() {
    if (current.key === "custom") return current.to;
    var view = data.recessionViews.filter(function (v) { return v.key === current.key; })[0];
    return view ? view.end : data.today;
  }
  function applyPageRange() {
    document.dispatchEvent(new CustomEvent("uw:range", { detail: { end: pageEnd() } }));
    return Promise.all(charts.map(function (c) { var w = windowFor(c); return setView(c, w[0], w[1]); }));
  }

  // ---------------------------------------------------------------- URL (so a shared link opens the same view)
  var VALID = ["1y", "2y", "5y", "10y", "20y", "max"].concat(data.recessionViews.map(function (v) { return v.key; }));
  function isDate(s) { return /^\d{4}-\d{2}-\d{2}$/.test(s || ""); }
  function readUrl() {
    var p = new URLSearchParams(window.location.search);
    var r = p.get("range"), from = p.get("from"), to = p.get("to");
    if (isDate(from) && isDate(to) && from < to) { current = { key: "custom", from: from, to: to }; }
    else if (VALID.indexOf(r) >= 0) { current = { key: r, from: null, to: null }; }
    if (p.get("view") === "weighted") document.documentElement.dataset.view = "weighted";
  }
  function writeUrl() {
    var p = new URLSearchParams(window.location.search);
    p.delete("range"); p.delete("from"); p.delete("to");
    if (current.key === "custom") { p.set("from", current.from); p.set("to", current.to); }
    else p.set("range", current.key);
    history.replaceState(null, "", window.location.pathname + "?" + p.toString() + window.location.hash);
  }

  // ---------------------------------------------------------------- time control buttons
  var tcButtons = document.querySelectorAll(".timecontrol > button[data-range]");
  var customForm = document.getElementById("tc-custom");
  function markButtons() {
    tcButtons.forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.range === current.key)); });
    if (current.key === "custom" && customForm) {
      customForm.hidden = false;
      customForm.elements.from.value = current.from;
      customForm.elements.to.value = current.to;
    }
  }
  tcButtons.forEach(function (b) {   // (pages without charts have no time control: nothing to wire up)
    b.addEventListener("click", function () {
      if (b.dataset.range === "custom") {
        customForm.hidden = !customForm.hidden;
        b.setAttribute("aria-expanded", String(!customForm.hidden));
        if (!customForm.hidden && !customForm.elements.from.value) {
          var w = baseWindow(charts.filter(function (c) { return !c.fixed; })[0] || charts[0]);
          customForm.elements.from.value = w[0];
          customForm.elements.to.value = w[1];
        }
        return;
      }
      current = { key: b.dataset.range, from: null, to: null };
      customForm.hidden = true;
      markButtons(); writeUrl(); applyPageRange();
    });
  });
  if (customForm) customForm.addEventListener("submit", function (e) {
    e.preventDefault();
    var from = customForm.elements.from.value, to = customForm.elements.to.value;
    if (!isDate(from) || !isDate(to) || from >= to) { customForm.elements.to.setCustomValidity("End date must be after the start date"); customForm.reportValidity(); return; }
    customForm.elements.to.setCustomValidity("");
    current = { key: "custom", from: from, to: to };
    markButtons(); writeUrl(); applyPageRange();
  });

  // ---------------------------------------------------------------- drawing
  function draw(chart) {
    var f = themed(chart.figure);
    var w = windowFor(chart);
    f.layout.xaxis.range = w;
    var config = { responsive: true, displayModeBar: false, doubleClick: false, displaylogo: false };
    return Plotly.newPlot(chart.el, f.data, f.layout, config).then(function (gd) {
      return setView(chart, w[0], w[1]).then(function () { return gd; });   // y-axis, visibility, labels
    }).then(function (gd) {
      // The reader zoomed one chart by dragging: rescale its y-axis to the new dates.
      gd.on("plotly_relayout", function (ev) {
        if (busy) return;
        // A drag-zoom reports "xaxis.range[0]" / "[1]". This script's own updates use "xaxis.range", so they are
        // ignored here; otherwise charts updating at the same time could keep re-triggering each other.
        var x0 = ev["xaxis.range[0]"], x1 = ev["xaxis.range[1]"];
        if (x0 !== undefined && x1 !== undefined) setView(chart, String(x0).slice(0, 10), String(x1).slice(0, 10));
      });
      // A legend click hid or showed a line: rescale to what's left.
      gd.on("plotly_restyle", function () {
        if (busy) return;
        var r = gd.layout.xaxis.range;
        setView(chart, String(r[0]).slice(0, 10), String(r[1]).slice(0, 10));
      });
      // Double-click returns this chart to the page setting.
      gd.addEventListener("dblclick", function () { var w2 = windowFor(chart); setView(chart, w2[0], w2[1]); });
    });
  }

  function redrawAll() {
    // Keep each chart's current x-range (it may be zoomed) while changing colors.
    return Promise.all(charts.map(function (c) {
      var r = c.el.layout && c.el.layout.xaxis.range.slice();
      var f = themed(c.figure);
      if (r) f.layout.xaxis.range = r;
      busy = true;
      return Plotly.react(c.el, f.data, f.layout).then(function () {
        busy = false;
        if (r) return setView(c, String(r[0]).slice(0, 10), String(r[1]).slice(0, 10));
      });
    }));
  }

  // ---------------------------------------------------------------- dark mode
  var toggle = document.getElementById("theme-toggle");
  function markToggle() {
    var dark = themeName() === "dark";
    toggle.setAttribute("aria-pressed", String(dark));
    toggle.querySelector(".theme-label").textContent = dark ? "Light mode" : "Dark mode";
  }
  toggle.addEventListener("click", function () {
    var next = themeName() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("uw-theme", next); } catch (e) { /* private browsing: just don't remember */ }
    markToggle(); redrawAll();
    document.dispatchEvent(new CustomEvent("uw:theme"));
  });
  phone.addEventListener("change", redrawAll);

  // ---------------------------------------------------------------- downloads
  function saveFile(name, blob) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }
  function csvCell(v) {
    if (v === null || v === undefined) return "";
    var s = String(v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  function downloadCsv(chart, scope) {
    var rows = chart.table.rows, name = chart.id;
    if (scope === "visible" && !chart.fixed) {
      var r = chart.el.layout.xaxis.range, x0 = String(r[0]).slice(0, 10), x1 = String(r[1]).slice(0, 10);
      rows = rows.filter(function (row) { return row[0] >= x0 && row[0] <= x1; });
      name += "_" + x0 + "_to_" + x1;
    } else {
      name += "_full_history";
    }
    var lines = [chart.table.columns.join(",")].concat(rows.map(function (row) { return row.map(csvCell).join(","); }));
    saveFile(name + ".csv", new Blob([lines.join("\r\n") + "\r\n"], { type: "text/csv" }));
  }
  function downloadPng(chart) {
    var gd = chart.el;
    var layout = Object.assign({}, gd.layout, {
      title: { text: chart.title + " · Unemployment Watch", x: 0.01, font: { size: 16 } },
      margin: Object.assign({}, gd.layout.margin, { t: 70 }),
      legend: Object.assign({}, gd.layout.legend, { y: 1.02 }),
      width: 1200, height: 600
    });
    Plotly.toImage({ data: gd.data, layout: layout }, { format: "png", width: 1200, height: 600 }).then(function (url) {
      fetch(url).then(function (r) { return r.blob(); }).then(function (b) { saveFile(chart.id + ".png", b); });
    });
  }
  function byId(id) { return charts.filter(function (c) { return c.id === id; })[0]; }

  document.addEventListener("click", function (e) {
    var t = e.target.closest("button");
    // close any open CSV menu when clicking elsewhere
    document.querySelectorAll(".menu-list").forEach(function (m) {
      if (!t || !m.parentNode.contains(t)) { m.hidden = true; m.parentNode.querySelector("[data-csv-menu]").setAttribute("aria-expanded", "false"); }
    });
    if (!t) return;
    if (t.dataset.csvMenu) {
      var list = t.parentNode.querySelector(".menu-list");
      list.hidden = !list.hidden;
      t.setAttribute("aria-expanded", String(!list.hidden));
    } else if (t.dataset.csv) {
      downloadCsv(byId(t.dataset.csv), t.dataset.scope);
      t.closest(".menu-list").hidden = true;
    } else if (t.dataset.png) {
      downloadPng(byId(t.dataset.png));
    }
  });
  // Review WP9 C7: the what-if numbers table under a chart follows the same toggle.
  function showWhatifTable(id, on) {
    document.querySelectorAll("[data-whatif-table='" + id + "']").forEach(function (t) { t.hidden = !on; });
  }
  // "Show what-if paths (not a forecast)": shows or hides the stress paths of one chart. They only appear in
  // today's view; while they show, the x-axis runs on to where they end.
  document.addEventListener("change", function (e) {
    var box = e.target.closest("input[data-whatif]");
    if (!box) return;
    var chart = byId(box.dataset.whatif);
    chart.whatif = box.checked;
    showWhatifTable(box.dataset.whatif, box.checked);
    var w = windowFor(chart);
    setView(chart, w[0], w[1]);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") document.querySelectorAll(".menu-list").forEach(function (m) { m.hidden = true; });
  });

  // What states.js uses: the end of the time setting, a redraw (after a view switch) and the theme colours.
  window.UW = { pageEnd: pageEnd, redraw: redrawAll, themeName: themeName, themes: THEMES };

  // ---------------------------------------------------------------- start
  readUrl();
  markButtons();
  markToggle();
  // A browser may restore a ticked what-if box after a reload: start from what the box shows.
  document.querySelectorAll("input[data-whatif]").forEach(function (b) {
    var c = byId(b.dataset.whatif);
    if (c) c.whatif = b.checked;
    showWhatifTable(b.dataset.whatif, b.checked);
  });
  Promise.all(charts.map(draw)).then(function () { document.body.dataset.ready = "true"; });
})();
