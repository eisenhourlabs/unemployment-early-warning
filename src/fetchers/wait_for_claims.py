"""
Thursday morning helper: wait until this week's jobless claims release is on FRED.

The weekly claims news release normally comes out Thursday at 8:30 am ET and reports initial claims for
the week ending the previous Saturday. FRED usually posts it within minutes, but not always before our
scheduled run. This script checks FRED's ICSA every few minutes until that week appears.

It never fails the run: if the week doesn't appear in time (e.g. a holiday schedule change or a
government shutdown with no release), it prints a note and exits normally, and the rest of the
workflow uses whatever data is available.

Run:  python src/fetchers/wait_for_claims.py            # defaults: check every 5 min, up to 60 min
      python src/fetchers/wait_for_claims.py 2 10       # every 2 min, up to 10 min
"""

import sys
import time
from datetime import date, timedelta

from fred_fetcher import fred_get, load_api_key


def expected_week(today: date) -> str:
    """The Saturday 5 days before this Thursday (the advance week); for other days, the most recent such Saturday."""
    target = today - timedelta(days=5)
    return (target - timedelta(days=(target.weekday() - 5) % 7)).isoformat()


def latest_icsa(key: str) -> str:
    obs = fred_get("series/observations", {"series_id": "ICSA", "sort_order": "desc", "limit": 1}, key)
    return obs["observations"][0]["date"]


def main(every_min: float = 5, max_min: float = 60) -> int:
    key = load_api_key()
    want = expected_week(date.today())
    deadline = time.monotonic() + max_min * 60
    while True:
        try:
            have = latest_icsa(key)
        except Exception as e:             # a FRED hiccup is not a reason to fail the run
            have = f"(error: {e})"
        if have >= want:
            print(f"Claims release is on FRED: latest ICSA week {have} (expected {want}).")
            return 0
        if time.monotonic() >= deadline:
            print(f"No new claims release after {max_min:g} minutes: latest ICSA week {have}, expected {want}. "
                  "Continuing without it (normal on holiday weeks or if no release is published).")
            return 0
        print(f"Waiting for claims release: latest ICSA week {have}, expected {want}; checking again in {every_min:g} min.")
        time.sleep(every_min * 60)


if __name__ == "__main__":
    sys.exit(main(*[float(a) for a in sys.argv[1:3]]))
