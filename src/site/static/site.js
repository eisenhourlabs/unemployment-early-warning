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
    return { id: c.id, title: c.title, figure: c.figure, table: c.table, fixed: c.fixed, zero: c.zero,
             el: document.getElementById("chart-" + c.id) };
  });
  var phone = window.matchMedia("(max-width: 759px)");
  var current = { key: data.defaultRange, from: null, to: null };   // the page's time setting

  // ---------------------------------------------------------------- colors per theme (same tokens as style.css)
  var THEMES = {
    light: { accent: "#2a78d6", faint: "rgba(42,120,214,0.35)", rgb: "42,120,214", bg: "#fcfcfb", text: "#52514e",
             greys: ["#6d6c67", "#93928c", "#b9b8b2"],
             grid: "#e8e7e3", axis: "#c8c7c2", recession: "rgba(120,120,120,0.16)", hoverBg: "#ffffff", hoverText: "#0b0b0b" },
    dark:  { accent: "#3987e5", faint: "rgba(57,135,229,0.40)", rgb: "57,135,229", bg: "#1a1a19", text: "#c3c2b7",
             greys: ["#b5b4ad", "#8a8983", "#62615c"],
             grid: "#2c2c29", axis: "#4a4a45", recession: "rgba(200,200,200,0.10)", hoverBg: "#262624", hoverText: "#f0efec" }
  };
  function themeName() { return document.documentElement.dataset.theme === "dark" ? "dark" : "light"; }

  // Return a copy of a chart's figure with the current theme's colors applied.
  function themed(fig) {
    var t = THEMES[themeName()];
    var f = JSON.parse(JSON.stringify(fig));
    f.data.forEach(function (tr) {
      var role = (tr.meta && tr.meta.role) || "";
      var color = role.indexOf("faint") === 0 ? t.faint
                : role.indexOf("grey") === 0 ? t.greys[+role.slice(4)] : t.accent;
      if (tr.line && role !== "fan-edge" && role !== "fan") tr.line.color = color;
      if (tr.marker) tr.marker.color = color;
      if (role === "fan") tr.fillcolor = "rgba(" + t.rgb + "," + tr.meta.alpha + ")";
    });
    var L = f.layout;
    L.paper_bgcolor = t.bg; L.plot_bgcolor = t.bg;
    L.font = Object.assign({}, L.font, { color: t.text });
    L.xaxis = Object.assign({}, L.xaxis, { linecolor: t.axis, tickcolor: t.axis });
    L.yaxis = Object.assign({}, L.yaxis, { gridcolor: t.grid });
    L.hoverlabel = { bgcolor: t.hoverBg, bordercolor: t.axis, font: { color: t.hoverText } };
    (L.shapes || []).forEach(function (s) {
      if (s.type === "line") s.line = Object.assign({}, s.line, { color: t.axis });   // zero lines
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
  function windowFor(chart) {
    if (chart.fixed) return chart.fixed;      // e.g. the seasonal chart: always Jan to Dec
    var k = current.key, today = data.today;
    var years = { "1y": 1, "2y": 2, "5y": 5, "10y": 10, "20y": 20 }[k];
    if (years) return [yearsBefore(today, years), today];
    if (k === "max") return [firstDate(chart), today];
    if (k === "custom") return [current.from, current.to];
    var view = data.recessionViews.filter(function (v) { return v.key === k; })[0];
    return view ? [view.start, view.end] : [yearsBefore(today, 5), today];
  }

  // Lowest and highest value of the visible lines between two dates, with a little padding.
  function yRange(gd, x0, x1, zero) {
    var lo = Infinity, hi = -Infinity;
    gd.data.forEach(function (tr) {
      if (tr.visible === false || tr.visible === "legendonly" || !tr.y) return;
      for (var i = 0; i < tr.x.length; i++) {
        var x = String(tr.x[i]).slice(0, 10), y = tr.y[i];
        if (y === null || y === undefined || x < x0 || x > x1) continue;
        if (y < lo) lo = y;
        if (y > hi) hi = y;
      }
    });
    if (lo === Infinity) return null;
    if (zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }   // bars and % changes keep the zero line in view
    var pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.1 || 1;
    return [lo - pad, hi + pad];
  }

  var busy = false;   // true while this script changes a chart, so our own changes don't trigger the listeners
  function setView(chart, x0, x1) {
    var gd = chart.el, y = yRange(gd, x0, x1, chart.zero);
    var update = { "xaxis.range": [x0, x1] };
    if (y) update["yaxis.range"] = y; else update["yaxis.autorange"] = true;
    busy = true;
    return Plotly.relayout(gd, update).then(function () { busy = false; }, function () { busy = false; });
  }
  function applyPageRange() {
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
          var w = windowFor(charts[0]);
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
      var y = yRange(gd, w[0], w[1], chart.zero);
      if (y) { busy = true; return Plotly.relayout(gd, { "yaxis.range": y }).then(function () { busy = false; return gd; }); }
      return gd;
    }).then(function (gd) {
      // The reader zoomed one chart by dragging: rescale its y-axis to the new dates.
      gd.on("plotly_relayout", function (ev) {
        if (busy) return;
        var x0 = ev["xaxis.range[0]"], x1 = ev["xaxis.range[1]"];
        if (x0 === undefined && ev["xaxis.range"]) { x0 = ev["xaxis.range"][0]; x1 = ev["xaxis.range"][1]; }
        if (x0 !== undefined) setView(chart, String(x0).slice(0, 10), String(x1).slice(0, 10));
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
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") document.querySelectorAll(".menu-list").forEach(function (m) { m.hidden = true; });
  });

  // ---------------------------------------------------------------- start
  readUrl();
  markButtons();
  markToggle();
  Promise.all(charts.map(draw)).then(function () { document.body.dataset.ready = "true"; });
})();
