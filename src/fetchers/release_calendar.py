"""
Release calendar: the next scheduled release dates shown on the dashboard's Overview page.

What it does:
  1. For the weekly claims report, the jobs report and JOLTS, it asks FRED which "release" a
     representative series belongs to, then asks FRED for that release's upcoming scheduled dates.
     (FRED publishes the official schedules, so nothing is typed in by hand.)
  2. For the Chicago Fed Labor Market Indicators (not on FRED) it reads the release-schedule table
     on the Chicago Fed's website.
  3. Writes data/processed/release_calendar.csv:
        release, next_date, following_date, detail, time_et, schedule_source, source_url

It never fails the run (exit code 0 always): the calendar is a convenience, not core data.
If a schedule can't be read, that row keeps a blank date and the site says "date not available".

Run:  python src/fetchers/release_calendar.py
"""

import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fred_fetcher import LOG_FILE, PROCESSED, fred_get, load_api_key  # noqa: E402

OUT = PROCESSED / "release_calendar.csv"

# Each release is looked up through one series that belongs to it.
# time_et = the usual release time (Eastern Time) published by DOL / BLS.
FRED_RELEASES = [
    {"release": "Weekly jobless claims", "series": "ICSA", "time_et": "8:30 am"},
    {"release": "Jobs report (unemployment rate, payrolls)", "series": "UNRATE", "time_et": "8:30 am"},
    {"release": "JOLTS (job openings, hires, layoffs)", "series": "JTSLDR", "time_et": "10:00 am"},
]

CHICAGO_URL = "https://www.chicagofed.org/research/data/chicago-fed-labor-market-indicators/release-schedule"
HEADERS = {"User-Agent": "unemployment-early-warning (github.com/eisenhourlabs/unemployment-early-warning)"}


def fred_dates(series_id: str, key: str, today: date) -> tuple[list[str], str, int]:
    """Upcoming release dates (as 'YYYY-MM-DD' strings) for the release that series_id belongs to."""
    rel = fred_get("series/release", {"series_id": series_id}, key)["releases"][0]
    result = fred_get("release/dates", {
        "release_id": rel["id"],
        "realtime_start": today.isoformat(),      # only dates from today onward...
        "realtime_end": "9999-12-31",
        "include_release_dates_with_no_data": "true",   # ...including future (scheduled) ones
        "sort_order": "asc",
        "limit": 5,
    }, key)
    return [d["date"] for d in result["release_dates"]], rel["name"], rel["id"]


def chicago_dates(today: date) -> list[tuple[str, str]]:
    """Read the Chicago Fed schedule table. Returns [(date 'YYYY-MM-DD', 'November 2026 advance'), ...]."""
    html = requests.get(CHICAGO_URL, headers=HEADERS, timeout=30).text
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)      # drop commented-out old rows
    # Each row looks like:  <td>November 2026<br /><span class="releaseType">Advance</span></td>
    #                       <td>Tuesday, November 24, 2026</td>
    pattern = re.compile(r"<td[^>]*>\s*([A-Z][a-z]+ \d{4})<br\s*/?>\s*<span class=\"releaseType\">(\w+)</span>"
                         r"\s*</td>\s*<td>\s*\w+, ([A-Z][a-z]+ \d{1,2}, \d{4})\s*</td>")
    rows = []
    for month, kind, when in pattern.findall(html):
        d = datetime.strptime(when, "%B %d, %Y").date()
        if d >= today:
            rows.append((d.isoformat(), f"{month} {kind.lower()}"))
    return sorted(rows)


def main() -> int:
    today = date.today()
    rows, log = [], []

    try:
        key = load_api_key()
    except SystemExit:
        key = None
    for r in FRED_RELEASES:
        row = {"release": r["release"], "next_date": "", "following_date": "", "detail": "",
               "time_et": r["time_et"], "schedule_source": "FRED release schedule", "source_url": ""}
        try:
            if key is None:
                raise RuntimeError("no FRED_API_KEY")
            dates, name, rel_id = fred_dates(r["series"], key, today)
            row["next_date"] = dates[0] if dates else ""
            row["following_date"] = dates[1] if len(dates) > 1 else ""
            row["detail"] = name
            row["source_url"] = f"https://fred.stlouisfed.org/releases/calendar?rid={rel_id}"
            log.append(("ok", r["release"]))
        except Exception as e:   # never stop the run for the calendar
            log.append((f"FAILED: {e}", r["release"]))
        rows.append(row)

    row = {"release": "Chicago Fed Labor Market Indicators", "next_date": "", "following_date": "",
           "detail": "", "time_et": "8:30 am", "schedule_source": "Chicago Fed release schedule",
           "source_url": CHICAGO_URL}
    try:
        found = chicago_dates(today)
        if found:
            row["next_date"], row["detail"] = found[0]
            if len(found) > 1:
                row["following_date"] = found[1][0]
        log.append(("ok" if found else "FAILED: no future dates in the schedule table", row["release"]))
    except Exception as e:
        log.append((f"FAILED: {e}", row["release"]))
    rows.append(row)

    pd.DataFrame(rows).to_csv(OUT, index=False)
    for status, name in log:
        print(f"  {name:<45} {status}")
    for r in rows:
        print(f"  {r['release']:<45} next {r['next_date'] or '(not available)'}  {r['detail']}")

    run_time = datetime.now(timezone.utc).isoformat(timespec="seconds")
    pd.DataFrame([{"run_utc": run_time, "series_id": f"CALENDAR:{n}", "status": s} for s, n in log]) \
        .to_csv(LOG_FILE, mode="a", header=not LOG_FILE.exists(), index=False)
    return 0   # always succeed


if __name__ == "__main__":
    sys.exit(main())
