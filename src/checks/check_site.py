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
Plus, on the first page: custom dates and dark mode. States page (Phase 4): map, tiles and table follow the end of
the time setting, the National / Weighted switch, sorting, hand-checked numbers and the wording rule. Phase 3 (Overview and Outlook): every colour has its text label
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
      if (y !== null && x > last && !m.forecast && !m.ref) last = x;   // reference lines are not data
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
    for href in [l for l in links if l.endswith(".csv") and ("/series/" in l or "/dol/" in l or "/states/" in l)]:
        got = pd.read_csv(SITE / href, dtype=str)
        if "/series/" in href:
            sid = Path(href).stem
            src = pd.read_csv(ROOT / "data" / "processed" / f"{sid}.csv", dtype=str).rename(columns={"value": sid})
        else:   # DOL files (data/processed/dol/) and the States page files (data/processed/states/)
            folder = "states" if "/states/" in href else "dol"
            src = pd.read_csv(ROOT / "data" / "processed" / folder / Path(href).name, dtype=str)
        if not got.fillna("").equals(src.fillna("")):
            mismatched.append(href)
    check(not mismatched, f"every series / DOL / state CSV equals its source file row for row {mismatched[:3]}")
    state_files = sorted(Path(l).name for l in links if "/states/" in l)
    check(state_files == sorted(f"{s}.{x}" for s in ("diffusion_weekly", "state_monthly", "state_weekly",
                                                      "weighted_monthly", "weighted_weekly")
                                for x in ("csv", "xlsx")), f"States downloads: {state_files}")
    leaks = [str(q.relative_to(SITE)) for q in (SITE / "data").rglob("*contribution*")]
    check(not leaks, f"weighted contributions (they list every weighted state) never offered {leaks[:3]}")
    bad_xlsx = []
    for href in [l for l in links if l.endswith(".xlsx")]:
        names = load_workbook(SITE / href, read_only=True).sheetnames
        want = (["Data", "Columns", "About"] if ("/dol/" in href or "/states/" in href or "dol_weekly" in href)
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
    dol_files = {Path(l).name for l in links if ("/dol/" in l or "/states/" in l) and l.endswith(".csv")}
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
    of states in the page files (since Phase 4 the States page shows counts of states meeting a condition, filled in
    by the browser in [data-count] elements only; check_states tests those), and "IUI" except where it is spelled out as
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
    # Review WP2 (2026-11): the 50%+ label is "High" on every page, never "More likely than not"
    old = [p.name for p in pages if re.search(r"(?i)more likely than not", p.read_text(encoding="utf-8"))]
    check(not old, f"no page says 'More likely than not' {old}")
    # Review WP9 (C1, C3, C6, C10, C11): statements the data do not support are gone from every page ...
    banned = r"(?i)before finding work|only the data known|reprinted with permission|every chart on this page|free-to-use"
    gone = [f"{p.name}: {m.group(0)}" for p in pages for m in re.finditer(banned, p.read_text(encoding="utf-8"))]
    check(not gone, f"no page says 'before finding work' / 'only the data known' / 'reprinted with permission' / "
                    f"'every chart on this page' / 'free-to-use' {gone[:3]}")
    # ... and the replacement sentences are where they belong (whitespace collapsed; HTML and chart data both read)
    wanted = {
        "index.html": ["except claims, which are today", "On claims as first published the 2022 readings would have",
                       "last 2 years (fixed view)", "this is the public guide to how often claims start (frequency)",
                       "this is the public guide to how long claims last (severity)"],
        "outlook.html": ["apart from later revisions to the claims figures (largest in 2022)",
                         "using only what was known then, apart from later revisions to the claims figures)"],
        "duration.html": ["It does not show whether they then found work.",
                          "It covers people receiving state benefits, not all unemployed people.",
                          "they rise with more new claims as well as with longer spells"],
        "job-losses.html": ["Claims are applications under state rules: a guide to direction and timing.",
                            "so layoffs can rise while payrolls still grow"],
        "about.html": ["State UI claims as a proxy", "indicators of direction and timing, not measures of that",
                       "Intended use: a regular briefing on labour-market conditions",
                       "not a basis on their own for pricing, reserving or risk limits",
                       "built from public data (one series is shown under its publisher"],
        "leading.html": ["retrieved from FRED, Federal Reserve Bank of St. Louis (https://fred.stlouisfed.org/series/UMCSENT/), accessed",
                         "Shown as a chart with this citation; the data are not offered for download here."],
    }
    missing = []
    for name, phrases in wanted.items():
        text = " ".join((SITE / name).read_text(encoding="utf-8").split())
        missing += [f"{name}: {w}" for w in phrases if w not in text]
    with_control = [p for p in pages if 'class="timecontrol"' in p.read_text(encoding="utf-8")]
    labelled = [p for p in with_control
                if 'aria-label="Time range for the charts on this page"' in p.read_text(encoding="utf-8")]
    check(not missing, f"review WP9 sentences present {missing[:3]}")
    check(with_control and len(labelled) == len(with_control),
          f"time control labelled 'Time range for the charts on this page' on {len(labelled)} of {len(with_control)} pages")
    # Phase 4 (brief): the States page also never says "employer" (other pages use "employers" in the ordinary
    # sense, e.g. "employers usually cut hours before they cut jobs"); the live page is checked in check_states.
    states_html = SITE / "states.html"
    if states_html.exists():
        check(not re.search(r"(?i)employer", states_html.read_text(encoding="utf-8")), "states.html never says 'employer'")


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
    # Review WP3: two FOMC markers, middle line to 6 months only (3 points), no nowcast, bands = live_latest.json
    traces = page.evaluate("""() => document.getElementById('chart-unemployment-rate').data.map(t => ({
        name: t.name || '', n: (t.x || []).length, y: t.y}))""")
    live_ur = json.loads((ROOT / "data" / "model" / "live_latest.json").read_text(encoding="utf-8"))
    fomc_names = [t["name"] for t in traces if t["name"].startswith("FOMC median")]
    check(len(fomc_names) == 2, f"Overview: 2 FOMC markers, this year's and next year's Q4 {fomc_names}")
    mid = [t for t in traces if t["name"] == "Forecast: middle line"]
    check(len(mid) == 1 and mid[0]["n"] == 3, f"Overview: middle line has 3 points (today, 3 and 6 months) {[t['n'] for t in mid]}")
    check(not any(t["name"].startswith("Nowcast") for t in traces), "Overview: no nowcast on the unemployment chart")
    fan = live_ur["fans"]["ur"]
    want_80 = [round(v, 6) for v in [fan["level"]] + [h["q10"] for h in fan["horizons"]]]
    got_80 = [[round(v, 6) for v in t["y"]] for t in traces if t["name"] == "Forecast: 80% band"]
    check(got_80 == [want_80], f"Overview: 80% band lower edge = live_latest.json fans ({got_80} vs {want_80})")
    ur_notes = " ".join(page.locator("#card-unemployment-rate .chart-note").all_inner_texts())
    check("Q4 2027" in ur_notes and "Nowcast" not in ur_notes and "nowcast" not in ur_notes,
          f"Overview: unemployment notes name Q4 2027 and no nowcast ({ur_notes[:120]!r})")
    for name in ("index.html", "duration.html"):
        check("50% and 80% of outcomes" not in (SITE / name).read_text(encoding="utf-8"),
              f"{name}: fan footer gives coverage as measured (no '50% and 80% of outcomes')")
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
    # Review WP2: what the score is, and is not
    panel_text = page.locator(".score-panel").inner_text()
    for words in ["stress alert, not a recession forecast", "claim frequency", "claim severity",
                  "chance of a claims jump or unemployment rise in the next 6 months"]:
        check(words in panel_text, f"Overview: score panel says '{words}'")
    check(page.locator(".score-panel .why a[href='duration.html']").count() == 1, "Overview: score definition links to Duration")
    check("new deterioration" not in (SITE / "index.html").read_text(encoding="utf-8"), "Overview: no 'new deterioration' in index.html")
    check("Backtest" not in panel_text, "Overview: score chart says 'Tested on history', not 'Backtest'")

    page.goto(base + "outlook.html")
    page.wait_for_selector("body[data-ready=true]")
    sig = labels()
    check(good(sig) and len(sig) >= 7, f"Outlook: {len(sig)} colours, each with its text label and icon")
    panel = page.locator("#trt-title ~ .table-scroll tbody tr:not(.muted)").count()
    context = page.locator("#trt-title ~ .table-scroll tbody tr.muted").count()
    check(panel == 5 and context == 2, f"Outlook: 5 panel triggers and 2 context rows ({panel}, {context})")
    body = page.inner_text("main")
    for words in ["long lead, often 12+ months", "real-time history only since 2011", "lower confidence",
                  "shown for context", "Tested on history (not live forecasts)", "Confirmation status:",
                  "Has deterioration already begun?", "Red on the Sahm indicator or new claims",
                  "44% on claims as first published", "about 1 red month in 5",
                  "does not measure the duration of unemployment"]:
        # text_content also reads the closed Methodology <details> blocks (inner_text skips hidden text)
        full = " ".join(page.locator("main").text_content().split())
        check(words in body or words in full, f"Outlook: says '{words}'")
    check(page.locator(".method details").count() >= 8, f"Outlook: {page.locator('.method details').count()} methodology sections")
    check(not re.search(r"\b(nan|NaN|None|undefined)\b", body), "Outlook: no 'nan' / 'None' in the page text")
    # Review WP2: one headline colour badge, the confirmation-trigger heading, the event table's new column
    head_badges = page.locator(".outlook-head .signal").count()
    check(head_badges == 1, f"Outlook: exactly one colour badge in the header section ({head_badges})")
    check(page.locator("#tr-title").inner_text().strip() == "Confirmation triggers", "Outlook: heading 'Confirmation triggers'")
    check(not re.search(r"Layer 1|[Ww]arning triggers|trigger 1 or 2", body), "Outlook: no 'Layer 1' / 'warning triggers' wording")
    ev = page.locator("#track table:not(#hit-rates)").first   # WP1: the hit-rate table comes first
    heads = [h.strip() for h in ev.locator("thead th").all_inner_texts()]
    rises = [t.strip() for t in ev.locator("tbody tr td:nth-child(4)").all_inner_texts()]
    check("Unemployment rise" in heads and len(rises) == 7, f"Outlook: event table has 'Unemployment rise' for 7 events {rises}")
    check(rises == ["+2.2 pt", "+0.5 pt", "+0.1 pt", "+5.6 pt", "+11.3 pt", "+0.5 pt", "+0.9 pt"],
          f"Outlook: unemployment rises match events.csv (#9-#15) {rises}")
    # Review WP1: the track record states the range, the first-published figure and the long 2022-2025 run, and the
    # hit-rate table (3 rows) matches data/model/score_skill_summary.csv
    track = " ".join(page.locator("#track").text_content().split())
    method = " ".join(page.locator(".method").first.text_content().split())     # closed <details> included
    for words in ["90% range", "as first published", "Episode counts understate long warnings"]:
        check(words in track, f"Outlook track record: says '{words}'")
    for words in ["38 months in a row", "so those results lean favourable"]:
        check(words in method, f"Outlook methodology: says '{words}'")
    check(page.locator("details#stretch-2022-2025").count() == 1, "Outlook: the 2022–2025 note has its anchor")
    # Review WP3: forecast-range wording, the split coverage columns, the nowcast row in the forecast table
    check("weakest when it mattered most" in method, "Outlook methodology: says 'weakest when it mattered most'")
    check("live ranges will react more slowly than the tests suggest" in method, "Outlook Limits: live-dating item")
    fan_heads = [h.strip() for h in page.locator("#track table").last.locator("thead th").all_inner_texts()]
    check("80%, before an event" in fan_heads and "80%, during an event" in fan_heads
          and "80%, around events" not in fan_heads, f"Outlook: backtest table splits coverage {fan_heads}")
    fc_rows = [" ".join(r.split()) for r in page.locator("#fc-title ~ .table-scroll tbody tr").all_inner_texts()]
    check(any("nowcast" in r and "9 times in 10" in r for r in fc_rows), "Outlook: forecast table has the nowcast row")
    check(any("12 months" in r and "FOMC Q4 2027" in r for r in fc_rows), "Outlook: 12-month row benchmarks FOMC Q4 2027")
    import csv
    with open(ROOT / "data" / "model" / "score_skill_summary.csv", encoding="utf-8") as f:
        rv = next(r for r in csv.DictReader(f) if r["basis"] == "revised")
    cells = [[c.strip() for c in r] for r in page.eval_on_selector_all(
        "#hit-rates tbody tr", "rows => rows.map(r => [...r.cells].map(c => c.innerText))")]
    want = [[str(int(rv[f"n_{k}"])), f"{float(rv[f'hit_{k}']) * 100:.0f}%"] for k in ("red", "amber", "green")]
    check(len(cells) == 3 and [c[1:] for c in cells] == want,
          f"Outlook: hit-rate table has 3 rows matching score_skill_summary.csv ({[c[1:] for c in cells]} vs {want})")
    live = json.loads((ROOT / "data" / "model" / "live_latest.json").read_text(encoding="utf-8"))
    page.goto(base + "index.html")
    page.wait_for_selector("body[data-ready=true]")
    change = page.locator(".score-change").inner_text()
    # Review WP9 C2: a first live run says only "First live run" (no arrow, no number); otherwise the line names
    # what it compares with. A delayed-claims suffix (" · provisional ...") may follow either.
    if live["score"].get("first_live_run"):
        ok = change.split(" · ")[0] == "First live run" and not re.search(r"[▲▼]|\d", change.split(" · ")[0])
    else:
        ok = "vs." in change or change == "no new claims data"
    check(ok and "backtest" not in change, f"Overview: the change line says what it compares with ({change!r})")
    # Review WP9 C5: the two rate tiles show the 4-week average, as in the latest row of the DOL rates file
    import csv
    with open(ROOT / "data" / "processed" / "dol" / "claims_rates_weekly.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    est_file = ROOT / "data" / "processed" / "dol" / "claims_estimates.csv"
    estimates_on = est_file.exists() and len(est_file.read_text(encoding="utf-8").strip().splitlines()) > 1
    tiles = {t.locator("h3").inner_text().strip(): t for t in page.locator(".tile").all()}
    for title, col, scale, unit in [("New claims rate, 4-week average", "ic_rate_sa_4wk", 100, " per 10k"),
                                    ("Continuing claims rate, 4-week average", "cc_rate_sa_4wk", 1, "%")]:
        if title not in tiles:
            check(False, f"Overview: tile '{title}' present ({list(tiles)})")
            continue
        got = tiles[title].locator(".tile-value").inner_text().strip()
        pct = tiles[title].locator(".tile-pct").inner_text().strip()
        if estimates_on:
            print(f"  (skipped value check for '{title}': estimated claims weeks are on file)")
        else:
            want = f"{float([r for r in rows if r[col]][-1][col]) * scale:.1f}{unit}"
            check(got == want, f"Overview: '{title}' tile = latest {col} in the DOL file ({got} vs {want})")
        check(pct.endswith("(rates before 1978 are not strictly comparable)"),
              f"Overview: '{title}' percentile line carries the 1978 note ({pct!r})")

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
    ctx = [c for c in cells if "Shown for context" in c["signal"]]
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


# ===========================================================================
# States page (Phase 4 stage 4b)
# ===========================================================================
def expected_snapshot(end: str) -> dict:
    """What the page should show for a time-setting end date, worked out here from site/assets/states.json the way
    states.js does: the last week (month) at or before the end in which at least 90% of the areas report."""
    import math
    P = json.loads((SITE / "assets" / "states.json").read_text(encoding="utf-8"))

    def last(arrays, keys, key):
        carriers = sum(any(v is not None for v in a) for a in arrays)
        need = math.ceil(0.9 * carriers)
        i = max((k for k, x in enumerate(keys) if x <= key), default=-1)
        while i >= 0 and sum(a[i] is not None for a in arrays) < need:
            i -= 1
        return i

    return {"P": P, "ic": last(P["w"]["icy"], P["weeks"], end), "cc": last(P["w"]["cc"], P["weeks"], end),
            "exh": last(P["m"]["exh"], P["months"], end[:7])}


def fmt_long(d: str) -> str:
    """2026-10-31 -> 'Oct 31, 2026' (the site's date format)."""
    y, m, dd = d.split("-")
    return f"{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][int(m) - 1]} {int(dd)}, {y}"


def signed(v: float, dec: int, unit: str) -> str:
    r = round(v, dec)
    return ("+" if r > 0 else "\u2212" if r < 0 else "") + f"{abs(r):,.{dec}f}{unit}"


def table_column(page, i: int) -> list:
    return page.evaluate(f"() => [...document.querySelectorAll('#state-table tbody tr')].map(r => r.cells[{i}].textContent)")


def as_numbers(vals: list) -> list:
    return [float(v.replace("\u2212", "-").replace("+", "").replace("%", "").replace(",", "")) for v in vals if v != "—"]


def check_states(browser, base) -> None:
    """Map, tiles and table follow the END of the time setting; the National / Weighted switch; sorting; the
    wording rule (no 'footprint' or 'employer', no exact weights, state counts only in [data-count] elements)."""
    import re
    import pandas as pd

    print("\n=== States page (map, tiles, table, views) ===")
    url = base + "states.html"
    page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(url)
    page.wait_for_selector("body[data-ready=true][data-states-ready=true]", timeout=30000)
    today = TODAY_OF(page)
    snap = expected_snapshot(today)
    P = snap["P"]
    week = P["weeks"][snap["ic"]]

    n_paths = page.locator("#states-map .choroplethlocation").count()
    check(n_paths == 51, f"map draws the states and DC ({n_paths} shapes)")
    asof = page.locator("#states-asof").text_content()
    check(fmt_long(week) in asof, f"'as of' line shows the latest complete week {fmt_long(week)}: {asof}")

    # Tile 1 by hand: the national year-on-year change in the data file for that week
    ww = pd.read_csv(ROOT / "data" / "processed" / "states" / "weighted_weekly.csv").set_index("week_ended")
    want = "National " + signed(ww.national_ic_yoy_pct[week], 1, "%")
    got = page.locator("#tile-icy [data-fill=value]").text_content()
    check(got == want, f"new-claims tile = data file ({got} vs {want})")
    # Table by hand: Texas 4-week average new claims and its continuing claims rate
    sw = pd.read_csv(ROOT / "data" / "processed" / "states" / "state_weekly.csv").set_index(["state", "week_ended"])
    tx = page.evaluate("""() => [...document.querySelectorAll('#state-table tbody tr')]
        .map(r => [...r.cells].map(c => c.textContent)).filter(c => c[0] === 'Texas')[0]""")
    want_ic = f"{sw.initial_claims_4wk[('TX', week)]:,.0f}"
    want_cc = f"{sw.cc_rate_4wk[('TX', P['weeks'][snap['cc']])]:.2f}%"
    check(tx[1] == want_ic and tx[5] == want_cc, f"Texas row = data file ({tx[1]}, {tx[5]} vs {want_ic}, {want_cc})")
    want_n = signed(sw.ic_vs_normal_pct[('TX', week)], 0, "%")
    check(tx[3] == want_n, f"Texas 'vs. normal' = data file ({tx[3]} vs {want_n})")
    cells = page.evaluate("""() => [...document.querySelectorAll('#state-table tbody td.num')].map(c => c.textContent)""")
    odd = [c for c in cells if not re.match(r"^(not reported|n/a|[−+]?[\d,.]+( pt|%)?( \(.+\))?)$", c)]
    check(not odd, f"every table value is a number (with its own date if older), 'not reported' or 'n/a' {odd[:3]}")
    n_spark = page.locator("#state-table svg.spark").count()
    check(n_spark >= 50, f"table sparklines drawn ({n_spark})")
    n_rows = page.locator("#state-table tbody tr").count()
    check(n_rows == len(P["areas"]), f"table has every area ({n_rows} rows)")
    texts = page.locator("main").inner_text()
    check(not re.search(r"\b(nan|NaN|undefined|null|None)\b", texts), "no blank-value words on the page")

    print("Sorting")
    page.click("#state-table th button[data-sort=icy]")
    nums = as_numbers(table_column(page, 2))
    check(nums == sorted(nums, reverse=True), f"sort by 'vs. yr ago': highest first ({nums[:3]})")
    page.click("#state-table th button[data-sort=icy]")
    nums = as_numbers(table_column(page, 2))
    check(nums == sorted(nums), "second click reverses it")
    check(page.locator("#state-table th[aria-sort=ascending] button[data-sort=icy]").count() == 1, "aria-sort set")

    print("Map measures")
    for m in P["measures"]:
        page.check(f"input[name=measure][value={m['key']}]")
        page.wait_for_timeout(250)
        footer = page.locator("#map-footer").text_content()
        n = page.locator("#states-map .choroplethlocation").count()
        check(footer.startswith(m["label"]) and n >= 51, f"measure '{m['label']}': map redrawn ({n} shapes)")
    page.check("input[name=measure][value=icy]")

    print("Time setting: the map, tiles and table follow its end")
    page.click(".timecontrol > button[data-range='2008-09']")
    page.wait_for_timeout(500)
    s08 = expected_snapshot("2011-12-31")
    w08 = fmt_long(P["weeks"][s08["ic"]])
    check(w08 in page.locator("#states-asof").text_content(), f"2008-09 view: tiles and map as of {w08}")
    dated = page.evaluate("() => document.querySelectorAll('#state-table .cell-date').length")
    check(w08 in page.locator("#table-asof").text_content() and dated < 40,
          f"2008-09 view: table as of {w08}; {dated} values carry an older date of their own")
    page.click(".timecontrol > button[data-range='5y']")
    page.wait_for_timeout(500)
    check(fmt_long(week) in page.locator("#states-asof").text_content(), "back to 5Y: latest week again")

    print("National / Weighted view")
    view_traces = "document.getElementById('chart-diffusion').data.filter(t => t.meta && t.meta.view).map(t => t.visible)"
    hidden = page.evaluate("[...document.querySelectorAll('[data-view-only=weighted]')].every(e => e.hidden)")
    dashed = page.evaluate(view_traces)
    check(hidden and dashed == [False], f"National view: weighted parts hidden, dashed line off ({dashed})")
    map_z = page.evaluate("document.getElementById('states-map').data[0].z")
    page.click("[data-view=weighted]")
    page.wait_for_timeout(600)
    shown = page.evaluate("[...document.querySelectorAll('[data-view-only=weighted]')].every(e => !e.hidden)")
    dashed = page.evaluate(view_traces)
    widths = page.evaluate("[...document.querySelectorAll('.weighted-section .chart')]"
                           ".map(e => Math.round(e.getBoundingClientRect().width))")
    check(shown and dashed == [True] and "view=weighted" in page.url,
          "Weighted view: parts shown, dashed line on, address ?view=weighted")
    check(all(w > 400 for w in widths), f"weighted charts drawn at full width ({widths})")
    n_dl = page.locator(".weighted-section [data-csv-menu]").count()
    check(n_dl == 4, f"weighted charts offer CSV downloads ({n_dl} of 4)")
    contrib = page.locator("#contrib-body tr").count()
    check(page.locator("#contributors").is_visible() and contrib >= 1, f"top-contributors table shown ({contrib} rows)")
    check(page.evaluate("document.getElementById('states-map').data[0].z") == map_z, "the map is the same in both views")
    page.goto(url + "?view=weighted&range=2020")
    page.wait_for_selector("body[data-ready=true][data-states-ready=true]")
    check(page.evaluate("[...document.querySelectorAll('.weighted-section')].every(e => !e.hidden)"),
          "shared link ?view=weighted opens the Weighted view")

    print("Review Gates 2-3: notes, lists, drill-down")
    import datetime as _dt
    ago = _dt.date.fromisoformat(week) - _dt.timedelta(days=364)
    want_note = (ago - _dt.timedelta(days=21)).isoformat() <= P["shutdownWeeks"][1] and ago.isoformat() >= P["shutdownWeeks"][0]
    page.goto(url)
    page.wait_for_selector("body[data-ready=true][data-states-ready=true]")
    check(page.locator("#shutdown-note").is_visible() == want_note, f"2025-shutdown note shown = {want_note}")
    check("context, not tested" in page.locator("#rising").inner_text(), "rising-states list labelled 'context, not tested'")
    check(page.locator("#rising .signal").count() == 0, "rising-states list has no red / amber / green")
    page.select_option("#drill-state", "OH")
    page.wait_for_timeout(500)
    n_drill = page.evaluate("() => [...document.querySelectorAll('.drill-chart')].filter(d => d.data && d.data.length).length")
    check("Ohio" in page.locator("#drill-title").inner_text() and n_drill == 5, f"drill-down: Ohio, {n_drill} of 5 charts")
    page.click("#state-table tbody tr:nth-child(3)")
    page.wait_for_timeout(500)
    first3 = table_column(page, 0)[2]
    check(first3 in page.locator("#drill-title").inner_text(), f"table row click opens the drill-down ({first3})")

    print("Wording (O1)")
    visible = page.evaluate("""() => { const c = document.querySelector('main').cloneNode(true);
        c.querySelectorAll('[data-count]').forEach(e => e.remove()); return c.innerText; }""")
    html = (SITE / "states.html").read_text(encoding="utf-8")
    payload = (SITE / "assets" / "states.json").read_text(encoding="utf-8")
    bad = [w for w in ("footprint", "employer", "branch") if re.search(w, visible + html, re.I)]
    check(not bad, f"States page never says {bad or 'footprint / employer / branch'}")
    counts = re.findall(r"\b\d+\s+states\b", visible, re.I)
    check(not counts, f"state counts only in the marked tile elements {counts[:3]}")
    weights = pd.read_csv(ROOT / "config" / "state_weights.csv", comment="#")
    leaked = [f"{w:.6f}" for w in weights.weight if f"{w:.6f}" in html or f"{w:.6f}" in payload]
    check(not leaked and '"weights"' not in payload and "rank" not in payload,
          f"no exact weight, weight list or rank in the page or its data file ({leaked[:2]})")

    print("Dark mode and phone")
    page.click("#theme-toggle")
    page.wait_for_timeout(500)
    bg = page.evaluate("document.getElementById('states-map').layout.paper_bgcolor")
    check(bg == "#1a1a19", f"dark mode: map redrawn dark ({bg})")
    page.screenshot(path=str(SHOTS / "states_weighted_dark.png"), full_page=True)
    page.click("#theme-toggle")
    pp = browser.new_context(viewport={"width": 400, "height": 860}, device_scale_factor=2,
                             is_mobile=True, has_touch=True).new_page()
    pp.goto(url)
    pp.wait_for_selector("body[data-states-ready=true]")
    right = pp.evaluate("Math.round(document.getElementById('states-map').getBoundingClientRect().right)")
    check(right <= 400, f"phone: map fits the screen (right edge {right} px)")
    check(not errors, f"no browser errors {errors[:3] if errors else ''}")
    page.context.close(); pp.context.close()


# ===========================================================================
# Shutdown fallback labels (Phase 4 stage 4c)
# ===========================================================================
def check_estimates(browser, base) -> None:
    """Normal build: no estimate wording anywhere. Build with estimated weeks (a real delay, or the PC preview
    UW_PREVIEW_DELAY=N): the freshness line, chart legends and hollow markers, the 'provisional' score note, the
    'What changed' sentences and the About method note all say so."""
    import re

    print("\n=== Shutdown fallback labels ===")
    pages = {p.name: p.read_text(encoding="utf-8") for p in SITE.glob("*.html")}
    active = "estimate (release delayed)" in pages["index.html"]
    check(bool(re.search(r"estimates\s+national claims from the state filings", pages["about.html"])),
          "About explains the fallback and its tested error")
    if not active:
        hits = [n for n, h in pages.items() if re.search(r"estimated from state filings ·|Estimate \(release delayed\)|"
                                                         r"Provisional: the score", h)]
        check(not hits, f"normal build: no estimate labels on any page {hits}")
        return
    page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
    page.goto(base + "index.html")
    page.wait_for_selector("body[data-ready=true]")
    fresh = page.locator(".freshness").inner_text()
    check("(last published)" in fresh and "estimated from state filings" in fresh, f"freshness line: {fresh[:160]}")
    note = page.locator(".score-panel .model-note").inner_text() if page.locator(".score-panel .model-note").count() else ""
    check("Provisional" in note, f"score panel says provisional: {note[:120]}")
    changes = page.locator(".changes").inner_text()
    check("estimated from state filings" in changes, "'What changed' marks estimated weeks")
    legends = page.evaluate("""() => [...document.querySelectorAll('.chart')].flatMap(gd => gd.data
        .filter(t => t.marker && t.marker.symbol === 'circle-open').map(t => t.name))""")
    check(any("estimate" in n.lower() for n in legends), f"hollow-marker traces labelled as estimates {legends[:3]}")
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
        check_estimates(browser, base)
        if "outlook.html" in links:
            check_phase3(browser, base)
        for i, href in enumerate(links):
            if href == "data.html":
                check_data_page(browser, base + href, base)
            elif href == "about.html":
                check_text_page(browser, base + href, href)
            else:
                check_page(browser, base + href, href, Path(href).stem, first_page=(i == 0))
                if href == "states.html":
                    check_states(browser, base)
        browser.close()

    print(f"\nScreenshots in {SHOTS}")
    print("ALL CHECKS PASSED" if not failures else f"{len(failures)} CHECK(S) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
