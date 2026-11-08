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
Plus, on the first page: custom dates and dark mode.
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
    if (tr.visible === 'legendonly' || !tr.y) return;
    tr.x.forEach((x, i) => {
      x = String(x).slice(0, 10); const y = tr.y[i];
      if (y !== null && x > last) last = x;
      if (y === null || x < r[0] || x > r[1]) return;
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


def expect_window(state, specs, x0, x1, label):
    """Every chart shows [x0, x1] (fixed-view charts keep their own range) and its y-axis hugs the
    visible data: covers it, includes zero where required, and adds no more than 25% extra."""
    for c, spec in zip(state, specs):
        want = spec["fixed"] or [x0, x1]
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
    pdata = json.loads(page.locator("#page-data").text_content())
    specs, today = pdata["charts"], pdata["today"]
    state = page.evaluate(STATE_JS)
    check(not errors, f"no browser errors {errors[:3] if errors else ''}")
    check(len(state) == len(specs) and len(state) > 0, f"{len(state)} charts drawn")
    for c, spec in zip(state, specs):
        rows = [r for r in spec["table"]["rows"] if r[2 if spec["fixed"] else 1] is not None]
        check(c["n"] > 10, f"{c['id']}: {c['n']} data points in view")
        if not spec["fixed"]:
            check(c["last"] == rows[-1][0], f"{c['id']}: last date on chart {c['last']} = last date in data {rows[-1][0]}")
    expect_window(state, specs, years_before(today, 5), today, "default 5Y")
    page.screenshot(path=str(SHOTS / f"{shots_prefix}_desktop.png"), full_page=True)

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
                want = spec["fixed"] or [spec["figure"]["data"][0]["x"][0], today]
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
        if spec["fixed"]:
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
    cols = pp.evaluate("getComputedStyle(document.querySelector('main .grid:last-of-type')).gridTemplateColumns")
    check(len(cols.split()) == 1, f"phone: charts in one column ({cols})")
    pp.screenshot(path=str(SHOTS / f"{shots_prefix}_phone.png"), full_page=True)
    check(not errors, f"no browser errors at the end {errors[:3] if errors else ''}")


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
        for i, href in enumerate(links):
            check_page(browser, base + href, href, Path(href).stem, first_page=(i == 0))
        browser.close()

    print(f"\nScreenshots in {SHOTS}")
    print("ALL CHECKS PASSED" if not failures else f"{len(failures)} CHECK(S) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
