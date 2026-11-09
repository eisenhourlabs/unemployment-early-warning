"""
Which DOL source kept publishing state weekly claims during the Oct 1 - Nov 12, 2025 federal shutdown?
(Phase 4 review, Gate 1a.) Evidence from the Internet Archive's saved copies (Wayback Machine):

  ar539.csv (oui.doleta.gov/unemploy/csv/)  - for every saved copy from Sep-Dec 2025: the latest week in the file and
                                              how many of the 53 areas had reported it. A copy saved mid-shutdown that
                                              holds a week ending during the shutdown means the file kept updating.
  claims.asp state report                   - a form (POST) page; the Archive can only hold its landing page, so this
                                              lists the saved copies and their dates only.
  data.dol.gov dataset 10306 (ETA 538 state weekly claims, API with a key) - lists saved copies of its page.

Runs in the "Probe shutdown sources" workflow (the Archive rate-limits home connections) or on the PC.
Run:  python src/checks/probe_shutdown_sources.py
"""

import io
import time

import pandas as pd
import requests

HEADERS = {"User-Agent": "unemployment-early-warning research probe (github.com/eisenhourlabs/unemployment-early-warning)"}
CDX = "https://web.archive.org/cdx/search/cdx"
SOURCES = {"ar539.csv": "oui.doleta.gov/unemploy/csv/ar539.csv",
           "claims.asp (state report pages)": "oui.doleta.gov/unemploy/claims.asp*",
           "claims report form target": "oui.doleta.gov/unemploy/wkclaims/report.asp*",
           "data.dol.gov dataset 10306": "data.dol.gov/datasets/10306*"}


def get(url, params=None, tries=6):
    for i in range(tries):
        r = requests.get(url, params=params, headers=HEADERS, timeout=180)
        if r.status_code == 200:
            return r
        print(f"    HTTP {r.status_code}, retrying in {20 * (i + 1)} s")
        time.sleep(20 * (i + 1))
    r.raise_for_status()


def snapshots(pattern: str) -> list[list[str]]:
    r = get(CDX, {"url": pattern, "from": "20250901", "to": "20251231", "fl": "timestamp,original,statuscode,length",
                  "filter": "statuscode:200", "collapse": "digest"})
    return [line.split(" ") for line in r.text.strip().splitlines() if line]


def main() -> None:
    for name, pattern in SOURCES.items():
        print(f"\n=== {name}: saved copies Sep-Dec 2025 (distinct contents) ===")
        rows = snapshots(pattern)
        if not rows:
            print("  none")
        for ts, original, status, length in rows:
            print(f"  {ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}  {length:>9} bytes  {original}")
        if name != "ar539.csv":
            continue
        print("\n  Contents of each saved ar539.csv (rptdate = week ending; areas = rows for that week):")
        for ts, original, *_ in rows:
            r = get(f"https://web.archive.org/web/{ts}id_/{original}")
            df = pd.read_csv(io.BytesIO(r.content), usecols=["st", "rptdate"], dtype=str)
            weeks = pd.to_datetime(df.rptdate, format="mixed")
            last = weeks.max()
            prev = weeks[weeks < last].max()
            print(f"    saved {ts[:4]}-{ts[4:6]}-{ts[6:8]}: latest week {last:%Y-%m-%d} "
                  f"({(weeks == last).sum()} areas), week before {prev:%Y-%m-%d} ({(weeks == prev).sum()} areas)")
            time.sleep(5)


if __name__ == "__main__":
    main()
