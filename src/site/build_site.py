"""
Build the Unemployment Watch website (a folder of plain HTML files) from our data files.

What it does, step by step:
  1. Builds each page's content with its own module:
       overview.py    -> index.html        (tiles, "What changed this week", 3 charts)
       job_losses.py  -> job-losses.html   (7 charts)
     Shared pieces (reading data, formats, chart builders) live in common.py.
  2. Adds the shared frame every page has: the freshness line, the stale-data badge (from the
     health check), the time control, the release calendar and the footer.
  3. Fills in the HTML templates in src/site/templates/ with Jinja2 (a fill-in-the-blanks tool:
     the template has {{ placeholders }} and Python supplies the values). Plotly charts are drawn in
     the reader's browser by plotly.js from the chart descriptions Python writes into each page.
  4. Writes everything to the site/ folder, which GitHub Pages publishes. site/ is rebuilt from
     scratch every time and is not stored in Git.

If anything goes wrong, the script stops with an error (exit code 1). In the cloud that means the
publish step is skipped and the previous version of the site stays online.

Run (from the project folder):
    python src/site/build_site.py
Preview:
    python -m http.server 8000 --directory site      then open http://localhost:8000
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly
from jinja2 import Environment, FileSystemLoader, select_autoescape

import job_losses
import overview
from common import PROCESSED, ROOT, claims_weekly, fmt_date, fmt_month, fred, is_preliminary

HERE = Path(__file__).resolve().parent
OUT = ROOT / "site"
REPO_URL = "https://github.com/eisenhourlabs/unemployment-early-warning"
CENTRAL = ZoneInfo("America/Chicago")

# Page-wide time control. Recession views run from about a year before each NBER recession to about
# two years after it ends (decision log, 2026-11-07).
RANGE_BUTTONS = [("1y", "1Y"), ("2y", "2Y"), ("5y", "5Y"), ("10y", "10Y"), ("20y", "20Y"), ("max", "Max")]
RECESSION_VIEWS = [
    {"key": "2001", "label": "2001", "start": "2000-01-01", "end": "2003-12-31"},
    {"key": "2008-09", "label": "2008–09", "start": "2007-01-01", "end": "2011-12-31"},
    {"key": "2020", "label": "2020", "start": "2019-01-01", "end": "2022-12-31"},
]
DEFAULT_RANGE = "5y"

# Top-bar links: (key, label, file). An empty file means "coming soon" (shown greyed out).
NAV = [("overview", "Overview", "index.html"), ("job-losses", "Job Losses", "job-losses.html"),
       ("duration", "Duration", ""), ("leading", "Leading", ""), ("data", "Data", ""), ("about", "About", "")]


# ===========================================================================
# The shared frame: freshness line, stale badge, release calendar
# ===========================================================================
def freshness(built: datetime) -> dict:
    claims = claims_weekly()

    def latest_week(rate_col, source_col, label):
        """'initial claims week ending Oct 31, 2026 (advance)'"""
        last = claims.dropna(subset=[rate_col]).iloc[-1]
        text = f"{label} week ending {fmt_date(last.week_ended)}"
        if is_preliminary(last[source_col]):
            text += " (" + last[source_col].split(",")[1].strip() + ")"
        return text

    ur = fred("UNRATE")
    local = built.astimezone(CENTRAL)
    return {
        "claims": latest_week("ic_rate_sa", "source_initial", "initial claims") + " · "
                  + latest_week("cc_rate_sa", "source_continued", "continuing claims"),
        "unemployment": f"unemployment rate {fmt_month(ur.index[-1])}",
        "updated": f"site updated {fmt_date(local)} {local:%I:%M %p}".replace(" 0", " ") + " CT",
    }


def stale_badge() -> dict | None:
    """Warning badge if the health check lists any stale or missing series."""
    path = PROCESSED / "series_health.csv"
    if not path.exists():
        return {"count": None, "text": "Data health check not available", "list": ""}
    h = pd.read_csv(path, dtype=str).fillna("")
    # h["flags"], not h.flags: pandas DataFrames already have a built-in attribute called .flags
    stale = h[h["flags"].str.contains("stale|no data", regex=True) | (h["status"] == "FAIL")]
    if stale.empty:
        return None
    names = ", ".join(stale.series_id.astype(str).tolist())
    n = len(stale)
    return {"count": n, "text": f"{n} series stale", "list": f"Stale or missing: {names}"}


def release_calendar() -> list[dict]:
    path = PROCESSED / "release_calendar.csv"
    if not path.exists():
        return []
    cal = pd.read_csv(path, dtype=str).fillna("")
    rows = []
    for r in cal.itertuples(index=False):
        next_txt = (f"{pd.Timestamp(r.next_date):%a}, {fmt_date(r.next_date)}" if r.next_date
                    else "date not available")
        rows.append({"release": r.release, "next": next_txt, "time": r.time_et + " ET" if r.next_date else "",
                     "detail": r.detail, "after": fmt_date(r.following_date) if r.following_date else "",
                     "url": r.source_url, "sort": r.next_date or "9999"})
    return sorted(rows, key=lambda x: x["sort"])


def page_data(charts: list[dict], built: datetime) -> str:
    """Everything the browser script (site.js) needs, embedded in the page as JSON."""
    return json.dumps({
        "today": built.astimezone(CENTRAL).strftime("%Y-%m-%d"),
        "defaultRange": DEFAULT_RANGE,
        "recessionViews": RECESSION_VIEWS,
        "charts": [{k: c[k] for k in ("id", "title", "figure", "table", "fixed", "zero")} for c in charts],
    }, separators=(",", ":"), allow_nan=False)


# ===========================================================================
# Write the site
# ===========================================================================
def main() -> None:
    built = datetime.now(timezone.utc)
    frame = {
        "nav": NAV,
        "freshness": freshness(built),
        "badge": stale_badge(),
        "range_buttons": RANGE_BUTTONS,
        "recession_views": RECESSION_VIEWS,
        "default_range": DEFAULT_RANGE,
        "repo_url": REPO_URL,
    }

    # Build every page's content before touching site/, so a failure leaves the old folder alone.
    ov = overview.build(built)
    jl = job_losses.build()
    pages = [
        ("overview.html", "index.html",
         {**frame, **ov, "page": "overview", "title": "Overview", "calendar": release_calendar(),
          "page_data": page_data(list(ov["charts"].values()), built)}, len(ov["charts"])),
        ("charts_page.html", "job-losses.html",
         {**frame, **jl, "page": "job-losses", "title": "Job Losses",
          "heading": "Job losses: how many people are losing jobs",
          "page_data": page_data(jl["charts"], built)}, len(jl["charts"])),
    ]

    # Start from an empty site/ folder so nothing old lingers.
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True)
    for f in (HERE / "static").iterdir():
        shutil.copy(f, OUT / "assets" / f.name)
    # plotly.js ships inside the Python plotly package, so the browser version always matches.
    shutil.copy(Path(plotly.__file__).parent / "package_data" / "plotly.min.js", OUT / "assets" / "plotly.min.js")

    env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=select_autoescape(["html"]))
    for template, out_name, context, n_charts in pages:
        (OUT / out_name).write_text(env.get_template(template).render(**context), encoding="utf-8")
        print(f"  {out_name:<18} {n_charts} charts")

    size_kb = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file()) / 1024
    print(f"Site built in {OUT} ({size_kb:,.0f} KB, {len(pages)} pages).")


if __name__ == "__main__":
    main()
