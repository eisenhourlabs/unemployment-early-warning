"""
Check the built website in a real browser (run on your PC after build_site.py).

It serves the site/ folder on a local address, opens every page linked in the top bar in Microsoft
Edge without a window (Playwright drives the browser), and checks on each page:
  1. the page loads with no browser errors;
  2. every chart has real data and its last date matches the data behind it;
  3. every time-control button sets every chart's dates (fixed-view charts stay put), rescales the
     y-axis to the visible data (keeping zero in view where it should), and records the range in the
     page address; a shared link opens the same range;
  4. the CSV and image downloads work;
  5. at phone width (400 px) nothing is wider than the screen and charts sit in one column.
Plus, on the first page: custom dates and dark mode. Phase 3 (Overview and Outlook): every colour has its text label
and icon; forecast elements (fans, nowcast, FOMC marker) show only when the time range includes today; the what-if
toggle shows and hides the stress paths.
Screenshots (desktop and phone, per page) are saved to the folder given (default: site_check/ in your
temp folder).

Setup once:  pip install -r requirements-dev.txt     (uses the Edge already installed on Windows)
Run:         python src/checks/check_site.py [screenshot folder]
Exit code 1 if any check fails.
"""

import functools
import http.server
import json
import sys
import tempfile
import threading
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.gettempdir()) / "site_check"

failures = []


def check(ok: bool, what: str) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {what}")
    if not ok:
        failures.append(what)


def serve() -> str:
    """Start a small web server for site/ on a free port, in the background. Returns its address."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    handler.log_message = lambda *a: None   # keep the output quiet
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}/"


# JavaScript run inside the page: for each chart, its x-range, y-range, and the min/max of the
# visible data between those dates (to confirm the y-axis was rescaled to the window).
STATE_JS = """() => [...document.querySelectorAll('.chart')].map(gd => {
  const r = gd.layout.xaxis.range.map(v => String(v).slice(0, 10));
  let lo = Infinity, hi = -Infinity, n = 0, last = '';
  gd.data.forEach(tr => {
    const m = tr.meta || {};
    if (tr.visible === 'legendonly' || tr.visible === false || !tr.y || m.noscale) return;
    tr.x.forEach((x, i) => {
      x = String(x).slice(0, 10); const y = tr.y[i];
      if (y !== null && x > last && !m.forecast) last = x;
      const always = tr.meta && tr.meta.ref;
      if (y === null || (!always && (x < r[0] || x > r[1]))) return;
      n++; lo = Math.min(lo, y); hi = Math.max(hi, y);
    });
  });
  return {id: gd.id, x: r, y: gd.layout.yaxis.range, lo, hi, n, last, bg: gd.layout.paper_bgcolor};
})"""


def years_before(d: str, n: int) -> str:
    y, m, dd = map(int, d.split("-"))
    try:
        return date(y - n, m, dd).isoformat()
    except ValueError:   # Feb 29
        return date(y - n, m, 28).isoformat()


TODAY = None   # the page's "today" (set per page)


def view_end(spec, x1, whatif=False):
    """Where a chart's x-axis should end: charts with a forecast run on to its end in today's view (and to the
    end of the what-if paths while those are shown), as site.js does."""
    ahead, wa = spec.get("ahead") or "", spec.get("whatif_ahead") or ""
    if not (ahead or wa) or x1 < TODAY:
        return x1
    end = wa if whatif and wa > ahead else (ahead or x1)
    return max(end, x1)


def first_x(spec):
    return min(str(tr["x"][0])[:10] for tr in spec["figure"]["data"] if tr.get("x"))


def expect_window(state, specs, x0, x1, label):
    """Every chart shows [x0, x1] (fixed-view charts keep their own range) and its y-axis hugs the
    visible data: covers it, includes zero where required, and adds no more than 25% extra."""
    for c, spec in zip(state, specs):
        want = spec["fixed"] or [x0, view_end(spec, x1)]
        check(c["x"] == want, f"{label}: {c['id']} shows {want[0]} to {want[1]} (got {c['x'][0]} to {c['x'][1]})")
        if c["n"]:
            lo, hi = c["lo"], c["hi"]
            if spec["zero"]:
                lo, hi = min(lo, 0), max(hi, 0)
            y0, y1 = c["y"]
            fits = y0 <= lo and y1 >= hi and (y1 - y0) <= (hi - lo) * 1.25 + 1e-9
            check(fits, f"{label}: {c['id']} y-axis {y0:.2f} to {y1:.2f} fits visible data {lo:.2f} to {hi:.2f}")


def check_page(browser, url, name, shots_prefix, first_page):
    page = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    print(f"\n=== {name} ===\nLoad")
    page.goto(url)
    page.wait_for_selector("body[data-ready=true]", timeout=30000)
    global TODAY
    pdata = json.loads(page.locator("#page-data").text_content())
    specs, today = pdata["charts"], pdata["today"]
    TODAY = today
    state = page.evaluate(STATE_JS)
    check(not errors, f"no browser errors {errors[:3] if errors else ''}")
    check(len(state) == len(specs) and len(state) > 0, f"{len(state)} charts drawn")
    for c, spec in zip(state, specs):
        rows = [r for r in spec["table"]["rows"] if r[2 if spec["fixed"] else 1] is not None]
        check(c["n"] > 10, f"{c['id']}: {c['n']} data points in view")
        if not spec["fixed"]:
            check(c["last"] == rows[-1][0], f"{c['id']}: last date on chart {c['last']} = last date in data {rows[-1][0]}")
    if pdata["defaultRange"] == "max":
        for c, spec in zip(state, specs):
            want = spec["fixed"] or [first_x(spec), view_end(spec, today)]
            check(c["x"] == want, f"default Max: {c['id']} shows {want[0]} to {want[1]} (got {c['x']})")
    else:
        expect_window(state, specs, years_before(today, 5), today, "default 5Y")
    page.screenshot(path=str(SHOTS / f"{shots_prefix}_desktop.png"), full_page=True)

    print("Drag-zoom and no runaway redraws")
    target = next(s for s in specs if not s["fixed"])["id"]
    baseline_x0 = next(c for c in state if c["id"] == f"chart-{target}")["x"][0]
    page.locator(f"#chart-{target}").scroll_into_view_if_needed()   # the mouse can only drag what is on screen
    box = page.locator(f"#chart-{target} .nsewdrag").bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.55, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.85, box["y"] + box["height"] / 2, steps=8)
    page.mouse.up()
    page.wait_for_timeout(600)
    zoomed = next(c for c in page.evaluate(STATE_JS) if c["id"] == f"chart-{target}")
    check(zoomed["x"][0] > baseline_x0, f"drag-zoom on {target} narrows the dates ({zoomed['x']})")
    if zoomed["n"]:
        fits = zoomed["y"][0] <= zoomed["lo"] and zoomed["y"][1] >= zoomed["hi"]
        check(fits, f"drag-zoom on {target} rescales the y-axis to the zoomed dates")
    # Count chart updates over one second: a settled page makes none (a feedback loop would make many).
    n_updates = page.evaluate("""() => new Promise(done => {
      let n = 0; document.querySelectorAll('.chart').forEach(gd => gd.on('plotly_relayout', () => n++));
      setTimeout(() => done(n), 1000); })""")
    check(n_updates == 0, f"no chart keeps redrawing itself ({n_updates} updates in 1 second)")
    page.goto(url)
    page.wait_for_selector("body[data-ready=true]")

    print("Time control buttons")
    views = {v["key"]: (v["start"], v["end"]) for v in pdata["recessionViews"]}
    for key, years in [("1y", 1), ("2y", 2), ("10y", 10), ("20y", 20), ("max", None)] + [(k, None) for k in views]:
        page.click(f".timecontrol > button[data-range='{key}']")
        page.wait_for_timeout(300)
        state = page.evaluate(STATE_JS)
        check(f"range={key}" in page.url, f"{key}: address records ?range={key}")
        if key in views:
            expect_window(state, specs, *views[key], key)
        elif years:
            expect_window(state, specs, years_before(today, years), today, key)
        else:   # Max: each chart from its own first date
            for c, spec in zip(state, specs):
                want = spec["fixed"] or [first_x(spec), view_end(spec, today)]
                check(c["x"] == want, f"max: {c['id']} shows {want[0]} to {want[1]} (got {c['x']})")

    print("Shared link")
    page.goto(url + "?range=2008-09")
    page.wait_for_selector("body[data-ready=true]")
    expect_window(page.evaluate(STATE_JS), specs, *views["2008-09"], "link ?range=2008-09")
    page.screenshot(path=str(SHOTS / f"{shots_prefix}_2008.png"), full_page=True)

    print("Downloads")
    for spec in specs:   # licensed charts must not offer any download
        if not spec.get("downloadable", True):
            n_buttons = page.locator(f"[data-csv-menu='{spec['id']}'], [data-png='{spec['id']}']").count()
            check(n_buttons == 0, f"{spec['id']}: no download buttons (licensed data)")
    normal = next(s for s in specs if not s["fixed"] and s.get("downloadable", True))["id"]
    page.click(f"[data-csv-menu='{normal}']")
    with page.expect_download() as dl:
        page.click(f"[data-csv='{normal}'][data-scope='visible']")
    lines = Path(dl.value.path()).read_text().strip().splitlines()
    dates = [l.split(",")[0] for l in lines[1:]]
    check(len(lines) > 10 and dates[0] >= "2007-01-01" and dates[-1] <= "2011-12-31",
          f"CSV visible range ({normal}): {len(lines) - 1} rows, {dates[0]} to {dates[-1]}")
    for spec in specs:
        if spec["fixed"] and spec.get("downloadable", True):
            page.click(f"[data-csv-menu='{spec['id']}']")
            with page.expect_download() as dl:
                page.click(f"[data-csv='{spec['id']}'][data-scope='full']")
            n = len(Path(dl.value.path()).read_text().strip().splitlines()) - 1
            check(n == len(spec["table"]["rows"]), f"CSV years shown ({spec['id']}): {n} rows")
    with page.expect_download() as dl:
        page.click(f"[data-png='{normal}']")
    png = Path(dl.value.path()).read_bytes()
    check(png[:4] == b"\x89PNG" and len(png) > 20000, f"PNG image: {len(png) / 1024:.0f} KB")

    if first_page:
        print("Custom dates")
        page.click(".timecontrol > button[data-range='custom']")
        page.fill("#tc-custom input[name=from]", "2015-03-01")
        page.fill("#tc-custom input[name=to]", "2019-06-30")
        page.click("#tc-custom button[type=submit]")
        page.wait_for_timeout(300)
        check("from=2015-03-01" in page.url and "to=2019-06-30" in page.url, "custom: address records from/to")
        expect_window(page.evaluate(STATE_JS), specs, "2015-03-01", "2019-06-30", "custom")

        print("Dark mode")
        page.goto(url)
        page.wait_for_selector("body[data-ready=true]")
        page.click("#theme-toggle")
        page.wait_for_timeout(500)
        theme = page.evaluate("document.documentElement.dataset.theme")
        bgs = {c["bg"] for c in page.evaluate(STATE_JS)}
        check(theme == "dark" and bgs == {"#1a1a19"}, f"dark mode: page {theme}, charts {bgs}")
        expect_window(page.evaluate(STATE_JS), specs, years_before(today, 5), today, "dark mode keeps 5Y")
        page.reload()
        page.wait_for_selector("body[data-ready=true]")
        check(page.evaluate("document.documentElement.dataset.theme") == "dark", "dark mode remembered after reload")
        page.click("#theme-toggle")   # back to light

    print("Phone width (400 px)")
    pp = browser.new_context(viewport={"width": 400, "height": 860}, device_scale_factor=2,
                             is_mobile=True, has_touch=True).new_page()
    pp.on("pageerror", lambda e: errors.append(str(e)))
    pp.goto(url)
    pp.wait_for_selector("body[data-ready=true]")
    overflow = pp.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    check(overflow <= 0, f"phone: page is not wider than the screen (overflow {overflow} px)")
    widths = pp.evaluate("[...document.querySelectorAll('.card')].map(c => Math.round(c.getBoundingClientRect().right))")
    check(max(widths) <= 400, f"phone: every card fits within 400 px (rightmost edge {max(widths)} px)")
    cols = pp.evaluate("getComputedStyle([...document.querySelectorAll('main .grid')].pop()).gridTemplateColumns")
    check(len(cols.split()) == 1, f"phone: charts in one column ({cols})")
    try:   # a review aid, not a check: a very tall page can exceed what a low-memory PC can capture
        pp.screenshot(path=str(SHOTS / f"{shots_prefix}_phone.png"), full_page=True)
    except Exception as e:
        print(f"  note  phone screenshot not saved ({str(e).splitlines()[0]})")
    check(not errors, f"no browser errors at the end {errors[:3] if errors else ''}")
    page.context.close(); pp.context.close()   # free the memory before the next page (low-memory PCs)


def check_data_page(browser, url, base):
    """Data & Downloads page: links, file contents, filters, licence exclusions, phone layout."""
    import urllib.request

    import pandas as pd
    from openpyxl import load_workbook

    print(f"\n=== data.html ===\nLoad")
    page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(url)
    page.wait_for_selector("#row-count")
    check(not errors, f"no browser errors {errors[:3] if errors else ''}")
    check(page.locator(".timecontrol").count() == 0, "no time control on a page without charts")

    print("Filters")
    total = page.locator("table.files tbody tr").count()
    visible = lambda: page.locator("table.files tbody tr:not([hidden])").count()
    n_state = page.locator("table.files tbody tr[data-state]:not([data-state=''])").count()
    check(visible() == total - n_state, f"default view hides the {n_state} state series ({visible()} of {total} shown)")
    page.check("input[name=states]")
    check(visible() == total, f"'Show state series' shows all {total}")
    page.fill("input[name=q]", "icsa")
    check(0 < visible() < 5, f"search 'icsa' narrows to {visible()} rows")
    page.fill("input[name=q]", "")
    page.select_option("select[name=frequency]", "monthly")
    rows = page.locator("table.files tbody tr:not([hidden])")
    freqs = set(page.eval_on_selector_all("table.files tbody tr:not([hidden])", "els => els.map(e => e.dataset.frequency)"))
    check(freqs == {"monthly"}, f"frequency filter: {rows.count()} monthly rows only ({freqs})")
    page.select_option("select[name=frequency]", "")
    page.uncheck("input[name=states]")
    page.screenshot(path=str(SHOTS / "data_desktop.png"), full_page=True)

    print("Every download link")
    links = page.eval_on_selector_all("a[download]", "els => els.map(e => e.getAttribute('href'))")
    bad = []
    for href in links:
        try:
            with urllib.request.urlopen(base + href, timeout=30) as r:
                if r.status != 200:
                    bad.append(href)
        except Exception as e:
            bad.append(f"{href} ({e})")
    check(not bad, f"{len(links)} download links all answer {bad[:3] if bad else ''}")

    print("File contents")
    mismatched = []
    for href in [l for l in links if l.endswith(".csv") and ("/series/" in l or "/dol/" in l)]:
        got = pd.read_csv(SITE / href, dtype=str)
        if "/series/" in href:
            sid = Path(href).stem
            src = pd.read_csv(ROOT / "data" / "processed" / f"{sid}.csv", dtype=str).rename(columns={"value": sid})
        else:
            src = pd.read_csv(ROOT / "data" / "processed" / "dol" / Path(href).name, dtype=str)
        if not got.fillna("").equals(src.fillna("")):
            mismatched.append(href)
    check(not mismatched, f"every series / DOL CSV equals its source file row for row {mismatched[:3]}")
    bad_xlsx = []
    for href in [l for l in links if l.endswith(".xlsx")]:
        names = load_workbook(SITE / href, read_only=True).sheetnames
        want = (["Data", "Columns", "About"] if ("/dol/" in href or "dol_weekly" in href)
                else ["Daily", "Weekly (Sat)", "Weekly (Fri)", "Monthly", "Dictionary"] if "everything" in href else ["Data", "About"])
        if names != want:
            bad_xlsx.append(f"{href}: {names}")
    check(not bad_xlsx, f"every XLSX opens with the expected sheets {bad_xlsx[:3]}")

    print("Data dictionary and table columns")
    headers = page.eval_on_selector_all("table.files thead th", "els => els.map(e => e.textContent.trim())")
    check(all(h in headers for h in ["Latest value", "Date", "Updated / checked"]),
          f"table columns include Latest value, Date, Updated / checked ({headers})")
    dd_path = SITE / "data" / "data_dictionary.csv"
    dd = pd.read_csv(dd_path) if dd_path.exists() else pd.DataFrame()
    check(list(dd.columns) == ["file", "column", "definition", "units"],
          f"data/data_dictionary.csv has file, column, definition, units ({list(dd.columns)})")
    dol_rows = page.locator("table.files tbody tr[data-kind='DOL']")
    n_dol = dol_rows.count()
    linked = page.locator("table.files tbody tr[data-kind='DOL'] a[href='data/data_dictionary.csv']").count()
    check(n_dol > 0 and linked == n_dol, f"all {n_dol} DOL rows link to the data dictionary ({linked} linked)")
    dol_files = {Path(l).name for l in links if "/dol/" in l and l.endswith(".csv")}
    missing = sorted(dol_files - set(dd["file"])) if len(dd) else sorted(dol_files)
    blank = int(dd["definition"].isna().sum() + dd["units"].isna().sum()) if len(dd) else -1
    check(not missing and blank == 0, f"dictionary covers every DOL file, no blank definitions or units {missing}")
    header = next(load_workbook(SITE / "data" / "dol" / "ar539.xlsx", read_only=True)["Columns"].iter_rows(values_only=True))
    check("units" in header, f"DOL XLSX Columns sheet has a units column ({header})")

    print("Licence exclusions")
    with open(ROOT / "config" / "series_catalog.csv", newline="") as f:
        import csv as _csv
        blocked = [r["series_id"] for r in _csv.DictReader(f) if r["license"] != "public"]
    blocked += ["CFLMI"]   # the Chicago Fed LMI files are saved as CFLMI*.csv
    leaks = [str(p.relative_to(SITE)) for p in (SITE / "data").rglob("*") if any(b in p.name for b in blocked)]
    for p in (SITE / "data" / "bundles").glob("*.csv"):
        header = p.open().readline()
        leaks += [f"{p.name}: column {b}" for b in blocked if b in header]
    check(not leaks, f"no restricted / unconfirmed series in any download ({', '.join(blocked)}) {leaks[:3]}")

    print("Phone width (400 px)")
    pp = browser.new_context(viewport={"width": 400, "height": 860}, device_scale_factor=2,
                             is_mobile=True, has_touch=True).new_page()
    pp.goto(url)
    pp.wait_for_selector("#row-count")
    overflow = pp.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    check(overflow <= 0, f"phone: page is not wider than the screen (overflow {overflow} px; the table scrolls inside its box)")
    pp.screenshot(path=str(SHOTS / "data_phone.png"), full_page=False)
    check(not errors, f"no browser errors at the end {errors[:3] if errors else ''}")
    page.context.close(); pp.context.close()   # free the memory before the next page (low-memory PCs)


def check_text_page(browser, url, name):
    """A page without charts (e.g. About): loads cleanly, in-page links resolve, fits a phone screen."""
    print(f"\n=== {name} ===")
    page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(url)
    page.wait_for_load_state("networkidle")
    check(not errors, f"no browser errors {errors[:3] if errors else ''}")
    check(page.locator(".timecontrol").count() == 0, "no time control on a page without charts")
    anchors = page.eval_on_selector_all("a[href^='#']", "els => els.map(e => e.getAttribute('href').slice(1))")
    missing = [a for a in anchors if page.locator(f"[id='{a}']").count() == 0]
    check(not missing, f"{len(anchors)} in-page links all lead somewhere {missing}")
    issues = page.eval_on_selector_all("a[href*='/issues/new']", "els => els.map(e => e.href)")
    check(len(issues) >= 1, f"'Report a problem' link present: {issues[:1]}")
    page.screenshot(path=str(SHOTS / f"{Path(name).stem}_desktop.png"), full_page=True)
    pp = browser.new_context(viewport={"width": 400, "height": 860}, device_scale_factor=2,
                             is_mobile=True, has_touch=True).new_page()
    pp.goto(url)
    pp.wait_for_load_state("networkidle")
    overflow = pp.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    check(overflow <= 0, f"phone: page is not wider than the screen (overflow {overflow} px)")
    pp.screenshot(path=str(SHOTS / f"{Path(name).stem}_phone.png"), full_page=False)
    page.context.close(); pp.context.close()   # free the memory before the next page (low-memory PCs)


def check_wording() -> None:
    """Words that must not appear on any public page (review 2026-11-07): the term "footprint" and any count
    of states until Phase 4, and "IUI" except where it is spelled out as
    "involuntary unemployment insurance (IUI)". Scans each page's full HTML, including the chart data."""
    import re

    print("\n=== Wording on every page ===")
    pages = sorted(SITE.glob("*.html"))
    hits = []
    for p in pages:
        text = p.read_text(encoding="utf-8")
        for pattern, why in [(r"(?i)footprint", "the word footprint"),
                             (r"\b\d+\s+(?:footprint\s+)?states\b", "a count of states"),
                             (r"\(\s*132\s*\)|\b132 state", "the number of state series")]:
            for m in re.finditer(pattern, text):
                hits.append(f"{p.name}: {why}: ...{text[max(0, m.start() - 40):m.end() + 20]}...")
        n_iui = len(re.findall(r"\bIUI\b", text))
        n_spelled = text.count("involuntary unemployment insurance (IUI)")
        if n_iui != n_spelled:
            hits.append(f"{p.name}: {n_iui - n_spelled} 'IUI' without 'involuntary unemployment insurance (IUI)'")
    check(not hits, f"{len(pages)} pages free of 'footprint', state counts and unexplained 'IUI' {hits[:3]}")


# For each chart: visibility of its forecast elements (meta.today) and what-if paths (meta.whatif), and its x-range.
TODAY_JS = """() => [...document.querySelectorAll('.chart')].map(gd => ({id: gd.id,
  today: gd.data.filter(t => t.meta && t.meta.today && !t.meta.whatif).map(t => t.visible === undefined ? true : t.visible),
  whatif: gd.data.filter(t => t.meta && t.meta.whatif).map(t => t.visible === undefined ? true : t.visible),
  x: gd.layout.xaxis.range.map(v => String(v).slice(0, 10))}))"""


def check_phase3(browser, base) -> None:
    """Early-warning score (Overview, Outlook): colour labels, 'as of' lines, forecast elements only in today's view,
    the what-if toggle, and no blank-value words ('nan', 'None') anywhere on the two pages."""
    import re

    print("\n=== Phase 3: early-warning score and forecast elements ===")
    page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base + "index.html")
    page.wait_for_selector("body[data-ready=true]")
    pdata = json.loads(page.locator("#page-data").text_content())
    ur_spec = next(s for s in pdata["charts"] if s["id"] == "unemployment-rate")

    def labels():
        return page.eval_on_selector_all(".signal", "els => els.map(e => e.textContent.trim().replace(/\\s+/g, ' '))")

    good = lambda ts: len(ts) >= 1 and all(re.fullmatch(r"[●▲■] (Green|Amber|Red)", t) for t in ts)
    sig = labels()
    check(good(sig), f"Overview: the colour shows its text label and icon {sig}")
    check(page.locator(".score-value").inner_text().strip() != "", "Overview: score value shown")
    check("As of" in page.locator(".score-asof").inner_text(), "Overview: score panel has its 'As of' line")
    check(page.locator(".drivers li").count() == 3, f"Overview: 3 drivers listed ({page.locator('.drivers li').count()})")
    check("early-warning score" in page.locator(".changes").inner_text(), "Overview: 'What changed' has the score sentence")

    def ur_state():
        return next(c for c in page.evaluate(TODAY_JS) if c["id"] == "chart-unemployment-rate")

    st = ur_state()
    check(len(st["today"]) >= 4 and all(v is True for v in st["today"]),
          f"5Y: fan, middle line and FOMC marker shown ({len(st['today'])} elements)")
    check(st["whatif"] and all(v is False for v in st["whatif"]), "5Y: what-if paths hidden until the box is ticked")
    check(st["x"][1] == ur_spec["ahead"], f"5Y: unemployment chart runs on to the forecast end {ur_spec['ahead']} (got {st['x'][1]})")
    for key in ["2008-09", "2001", "2020"]:
        page.click(f".timecontrol > button[data-range='{key}']")
        page.wait_for_timeout(300)
        st = ur_state()
        check(all(v is False for v in st["today"] + st["whatif"]), f"{key}: forecast elements hidden (history only)")
    page.click(".timecontrol > button[data-range='custom']")
    page.fill("#tc-custom input[name=from]", "2015-01-01")
    page.fill("#tc-custom input[name=to]", "2019-12-31")
    page.click("#tc-custom button[type=submit]")
    page.wait_for_timeout(300)
    check(all(v is False for v in ur_state()["today"]), "custom 2015-2019: forecast elements hidden")
    page.click(".timecontrol > button[data-range='1y']")
    page.wait_for_timeout(300)
    check(all(v is True for v in ur_state()["today"]), "1Y: forecast elements back")
    page.check("input[data-whatif='unemployment-rate']")
    page.wait_for_timeout(300)
    st = ur_state()
    check(st["whatif"] and all(v is True for v in st["whatif"]), "what-if box ticked: both what-if paths shown")
    check(st["x"][1] == ur_spec["whatif_ahead"], f"what-if shown: x-axis runs to {ur_spec['whatif_ahead']} (got {st['x'][1]})")
    page.screenshot(path=str(SHOTS / "overview_whatif.png"), full_page=False,
                    clip={"x": 0, "y": page.locator("#card-unemployment-rate").bounding_box()["y"], "width": 1280, "height": 620})
    page.click(".timecontrol > button[data-range='2008-09']")
    page.wait_for_timeout(300)
    check(all(v is False for v in ur_state()["whatif"]), "2008-09 with the box ticked: what-if paths still hidden")
    page.uncheck("input[data-whatif='unemployment-rate']")
    page.click(".timecontrol > button[data-range='5y']")
    page.wait_for_timeout(300)
    check(all(v is False for v in ur_state()["whatif"]), "box unticked: what-if paths hidden again")
    text = page.inner_text("main")
    check(not re.search(r"\b(nan|NaN|None|undefined)\b", text), "Overview: no 'nan' / 'None' in the page text")

    page.goto(base + "outlook.html")
    page.wait_for_selector("body[data-ready=true]")
    sig = labels()
    check(good(sig) and len(sig) >= 7, f"Outlook: {len(sig)} colours, each with its text label and icon")
    panel = page.locator("#trt-title ~ .table-scroll tbody tr:not(.muted)").count()
    context = page.locator("#trt-title ~ .table-scroll tbody tr.muted").count()
    check(panel == 5 and context == 2, f"Outlook: 5 panel triggers and 2 context rows ({panel}, {context})")
    body = page.inner_text("main")
    for words in ["long lead, often 12+ months", "real-time history only since 2011", "lower confidence",
                  "not counted in the overall status", "Backtest (tested on history; not live forecasts)"]:
        check(words in body, f"Outlook: says '{words}'")
    check(page.locator(".method details").count() >= 8, f"Outlook: {page.locator('.method details').count()} methodology sections")
    check(not re.search(r"\b(nan|NaN|None|undefined)\b", body), "Outlook: no 'nan' / 'None' in the page text")
    live = json.loads((ROOT / "data" / "model" / "live_latest.json").read_text(encoding="utf-8"))
    page.goto(base + "index.html")
    page.wait_for_selector("body[data-ready=true]")
    change = page.locator(".score-change").inner_text()
    want = "First live run" if live["score"].get("first_live_run") else "vs."
    check(want in change and ("backtest" in change) == bool(live["score"].get("first_live_run")),
          f"Overview: the change line says what it compares with ({change!r})")

    # ---- Stage 3e-2: claims pages ----
    for href, cid, has_fan in [("job-losses.html", "ic-rate", False), ("duration.html", "cc-rate", True)]:
        page.goto(base + href)
        page.wait_for_selector("body[data-ready=true]")
        spec = next(s for s in json.loads(page.locator("#page-data").text_content())["charts"] if s["id"] == cid)

        def st():
            return next(c for c in page.evaluate(TODAY_JS) if c["id"] == f"chart-{cid}")

        s0 = st()
        if has_fan:
            check(len(s0["today"]) >= 4 and all(v is True for v in s0["today"]), f"{href}: fan shown in 5Y")
            check(s0["x"][1] == spec["ahead"], f"{href}: chart runs on to the fan's end {spec['ahead']} (got {s0['x'][1]})")
        else:
            check(len(s0["today"]) == 0, f"{href}: no forecast fan on the initial-claims chart")
            check(s0["x"][1] == TODAY_OF(page), f"{href}: chart ends today while the what-if box is off (got {s0['x'][1]})")
        check(s0["whatif"] and all(v is False for v in s0["whatif"]), f"{href}: what-if paths hidden until ticked")
        page.check(f"input[data-whatif='{cid}']")
        page.wait_for_timeout(300)
        s1 = st()
        check(all(v is True for v in s1["whatif"]) and s1["x"][1] == spec["whatif_ahead"],
              f"{href}: what-if ticked shows both paths to {spec['whatif_ahead']} (got {s1['x'][1]})")
        page.click(".timecontrol > button[data-range='2008-09']")
        page.wait_for_timeout(300)
        s2 = st()
        check(all(v is False for v in s2["today"] + s2["whatif"]), f"{href}: 2008-09 view shows history only")
        notes = page.locator(f"#card-{cid} .chart-note").all_inner_texts()
        want = "52-week ranges are not shown" if has_fan else "We don't show a forecast range for initial claims"
        check(any(want in n for n in notes), f"{href}: note '{want}…' present")
        if not has_fan:
            check(any("In the early-warning score, new claims" in n for n in notes), f"{href}: score driver line present")
        check(not re.search(r"\b(nan|NaN|None|undefined)\b", page.inner_text("main")), f"{href}: no 'nan' / 'None'")

    # ---- Leading: signal colours and context labels ----
    page.goto(base + "leading.html")
    page.wait_for_selector("body[data-ready=true]")
    cells = page.eval_on_selector_all(".summary tbody tr", """rows => rows.map(r => ({
        name: r.cells[0].innerText.split('\\n')[0], signal: r.querySelector('.signal-cell').innerText.replace(/\\s+/g, ' ')}))""")
    by = lambda word: [c for c in cells if word.lower() in c["name"].lower()]
    yc, nf = by("Yield curve"), by("National Financial Conditions")
    check(len(yc) == 1 and re.match(r"[●▲■] (Green|Amber|Red)", yc[0]["signal"]) and "long lead" in yc[0]["signal"],
          f"Leading: yield curve has its colour and 'long lead' note {yc}")
    check(len(nf) == 1 and re.match(r"[●▲■] (Green|Amber|Red)", nf[0]["signal"]) and "since 2011" in nf[0]["signal"],
          f"Leading: NFCI has its colour and 'real-time only since 2011' note {nf}")
    ctx = [c for c in cells if "not counted in the overall status" in c["signal"]]
    check(len(ctx) == 3 and not any(re.search(r"Green|Amber|Red", c["signal"]) for c in ctx),
          f"Leading: temp help and the two factory surveys are context, with no colour ({len(ctx)} rows)")
    th = next((c for c in ctx if "Temporary-help" in c["signal"]), None)
    th_live = next(c for c in live["score"]["contributions"] if c["input"] == "temp_help")
    check(th is not None and th_live["sentence"] in th["signal"],
          f"Leading: temp help uses the Overview driver's wording ({th_live['sentence']!r})")

    # ---- Data & Downloads: model files ----
    from openpyxl import load_workbook
    page.goto(base + "data.html")
    links = page.eval_on_selector_all("#model a[download]", "els => els.map(e => e.getAttribute('href'))")
    check(len(links) == 10, f"Data: 5 model files as CSV and XLSX ({len(links)} links)")
    bad = []
    for href in [l for l in links if l.endswith(".xlsx")]:
        wb = load_workbook(SITE / href, read_only=True)
        about = [r for r in wb["About"].iter_rows(values_only=True)]
        if wb.sheetnames != ["Data", "About"] or not any("not official statistics" in str(r) for r in about):
            bad.append(href)
    check(not bad, f"Data: every model XLSX has an About sheet saying 'not official statistics' {bad}")
    check("UNRATEMD" in page.locator("#model").inner_text() and not any("UNRATEMD" in l for l in links),
          "Data: FOMC median named as a FRED reference, not offered as a file")
    page.goto(base + "about.html")
    check(page.locator("#updates a[href='outlook.html#methodology']").count() == 1, "About: Updates links to the methodology")
    about = page.inner_text("main")
    check("No forecast yet" not in about and page.locator("a[href='outlook.html']").count() >= 1,
          "About: no 'No forecast yet'; points to the Outlook page")
    check("manual" in about, "About: says which model steps are manual")
    check(not errors, f"no browser errors {errors[:3] if errors else ''}")
    page.context.close()


def TODAY_OF(page) -> str:
    return json.loads(page.locator("#page-data").text_content())["today"]


def main() -> int:
    if not (SITE / "index.html").exists():
        sys.exit("site/index.html not found: run python src/site/build_site.py first")
    SHOTS.mkdir(parents=True, exist_ok=True)
    base = serve()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        # Every page that has a real link in the top bar
        nav = browser.new_page()
        nav.goto(base)
        links = nav.eval_on_selector_all(".pages a[href]", "els => els.map(e => e.getAttribute('href'))")
        nav.close()
        check(len(links) >= 1, f"top bar links: {links}")
        check_wording()
        if "outlook.html" in links:
            check_phase3(browser, base)
        for i, href in enumerate(links):
            if href == "data.html":
                check_data_page(browser, base + href, base)
            elif href == "about.html":
                check_text_page(browser, base + href, href)
            else:
                check_page(browser, base + href, href, Path(href).stem, first_page=(i == 0))
        browser.close()

    print(f"\nScreenshots in {SHOTS}")
    print("ALL CHECKS PASSED" if not failures else f"{len(failures)} CHECK(S) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
