"""
Check the built website in a real browser (run on your PC after build_site.py).

It serves the site/ folder on a local address, opens it in Microsoft Edge without a window
(Playwright drives the browser), and checks:
  1. the page loads with no browser errors;
  2. every chart has real data and its last date matches the data files;
  3. every time-control button sets every chart's dates, rescales the y-axis to the visible data,
     and records the range in the page address; a shared link opens the same range;
  4. custom dates, dark mode, and the CSV and image downloads work;
  5. at phone width (400 px) nothing is wider than the screen.
Screenshots (desktop and phone, light and dark) are saved to the folder given (default: site_check/
in your temp folder).

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
      if (x > last) last = x;
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


def expect_window(state, x0, x1, label):
    """Every chart shows [x0, x1] and its y-axis hugs the visible data (no more than 25% extra)."""
    for c in state:
        check(c["x"] == [x0, x1], f"{label}: {c['id']} shows {x0} to {x1} (got {c['x'][0]} to {c['x'][1]})")
        if c["n"]:
            span = c["hi"] - c["lo"]
            y0, y1 = c["y"]
            fits = y0 <= c["lo"] and y1 >= c["hi"] and (y1 - y0) <= span * 1.25 + 1e-9
            check(fits, f"{label}: {c['id']} y-axis {y0:.2f}-{y1:.2f} fits visible data {c['lo']:.2f}-{c['hi']:.2f}")


def main() -> int:
    if not (SITE / "index.html").exists():
        sys.exit("site/index.html not found: run python src/site/build_site.py first")
    SHOTS.mkdir(parents=True, exist_ok=True)
    url = serve()
    page_data = None

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        print("Load")
        page.goto(url)
        page.wait_for_selector("body[data-ready=true]", timeout=30000)
        page_data = json.loads(page.locator("#page-data").text_content())
        today = page_data["today"]
        state = page.evaluate(STATE_JS)
        check(not errors, f"no browser errors {errors[:3] if errors else ''}")
        check(len(state) == len(page_data["charts"]) and len(state) > 0, f"{len(state)} charts drawn")
        for c, spec in zip(state, page_data["charts"]):
            want_last = spec["table"]["rows"][-1][0]
            check(c["n"] > 50, f"{c['id']}: {c['n']} data points in the default window")
            check(c["last"] == want_last, f"{c['id']}: last date on chart {c['last']} = last date in data {want_last}")
        expect_window(state, years_before(today, 5), today, "default 5Y")
        page.screenshot(path=str(SHOTS / "desktop_light.png"), full_page=True)

        print("Time control buttons")
        views = {v["key"]: (v["start"], v["end"]) for v in page_data["recessionViews"]}
        for key, years in [("1y", 1), ("2y", 2), ("10y", 10), ("20y", 20), ("max", None)] + [(k, None) for k in views]:
            page.click(f".timecontrol > button[data-range='{key}']")
            page.wait_for_timeout(300)
            state = page.evaluate(STATE_JS)
            check(f"range={key}" in page.url, f"{key}: address records ?range={key}")
            pressed = page.get_attribute(f".timecontrol > button[data-range='{key}']", "aria-pressed")
            check(pressed == "true", f"{key}: button shows as selected")
            if key in views:
                expect_window(state, *views[key], key)
            elif years:
                expect_window(state, years_before(today, years), today, key)
            else:   # Max: each chart from its own first date
                for c, spec in zip(state, page_data["charts"]):
                    first = spec["table"]["rows"][0][0]
                    check(c["x"] == [first, today], f"max: {c['id']} shows {first} to {today} (got {c['x']})")

        print("Shared link")
        page.goto(url + "?range=2008-09")
        page.wait_for_selector("body[data-ready=true]")
        expect_window(page.evaluate(STATE_JS), *views["2008-09"], "link ?range=2008-09")
        page.screenshot(path=str(SHOTS / "desktop_2008.png"), full_page=True)

        print("Custom dates")
        page.click(".timecontrol > button[data-range='custom']")
        page.fill("#tc-custom input[name=from]", "2015-03-01")
        page.fill("#tc-custom input[name=to]", "2019-06-30")
        page.click("#tc-custom button[type=submit]")
        page.wait_for_timeout(300)
        check("from=2015-03-01" in page.url and "to=2019-06-30" in page.url, "custom: address records from/to")
        expect_window(page.evaluate(STATE_JS), "2015-03-01", "2019-06-30", "custom")

        print("Downloads")
        first = page_data["charts"][1]["id"]
        page.click(f"[data-csv-menu='{first}']")
        with page.expect_download() as dl:
            page.click(f"[data-csv='{first}'][data-scope='visible']")
        lines = Path(dl.value.path()).read_text().strip().splitlines()
        dates = [l.split(",")[0] for l in lines[1:]]
        check(len(lines) > 100 and dates[0] >= "2015-03-01" and dates[-1] <= "2019-06-30",
              f"CSV visible range: {len(lines) - 1} rows, {dates[0]} to {dates[-1]}")
        page.click(f"[data-csv-menu='{first}']")
        with page.expect_download() as dl:
            page.click(f"[data-csv='{first}'][data-scope='full']")
        full = Path(dl.value.path()).read_text().strip().splitlines()
        check(len(full) - 1 == len(page_data["charts"][1]["table"]["rows"]), f"CSV full history: {len(full) - 1} rows")
        with page.expect_download() as dl:
            page.click(f"[data-png='{first}']")
        png = Path(dl.value.path()).read_bytes()
        check(png[:4] == b"\x89PNG" and len(png) > 20000, f"PNG image: {len(png) / 1024:.0f} KB")

        print("Dark mode")
        page.goto(url)
        page.wait_for_selector("body[data-ready=true]")
        page.click("#theme-toggle")
        page.wait_for_timeout(500)
        theme = page.evaluate("document.documentElement.dataset.theme")
        bgs = {c["bg"] for c in page.evaluate(STATE_JS)}
        check(theme == "dark" and bgs == {"#1a1a19"}, f"dark mode: page {theme}, charts {bgs}")
        expect_window(page.evaluate(STATE_JS), years_before(today, 5), today, "dark mode keeps 5Y")
        page.screenshot(path=str(SHOTS / "desktop_dark.png"), full_page=True)
        page.reload()
        page.wait_for_selector("body[data-ready=true]")
        check(page.evaluate("document.documentElement.dataset.theme") == "dark", "dark mode remembered after reload")
        page.click("#theme-toggle")   # back to light for the phone check

        print("Phone width (400 px)")
        phone = browser.new_context(viewport={"width": 400, "height": 860}, device_scale_factor=2,
                                    is_mobile=True, has_touch=True)
        pp = phone.new_page()
        pp.on("pageerror", lambda e: errors.append(str(e)))
        pp.goto(url)
        pp.wait_for_selector("body[data-ready=true]")
        overflow = pp.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        check(overflow <= 0, f"phone: page is not wider than the screen (overflow {overflow} px)")
        widths = pp.evaluate("[...document.querySelectorAll('.card')].map(c => Math.round(c.getBoundingClientRect().right))")
        check(max(widths) <= 400, f"phone: every card fits within 400 px (rightmost edge {max(widths)} px)")
        cols = pp.evaluate("getComputedStyle(document.querySelector('main .grid:not(.top-row)')).gridTemplateColumns")
        check(len(cols.split()) == 1, f"phone: charts in one column ({cols})")
        pp.screenshot(path=str(SHOTS / "phone_light.png"), full_page=True)
        check(not errors, f"no browser errors at the end {errors[:3] if errors else ''}")
        browser.close()

    print(f"\nScreenshots in {SHOTS}")
    print("ALL CHECKS PASSED" if not failures else f"{len(failures)} CHECK(S) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
