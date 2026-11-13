"""
Live scorecard (review WP4, Part C): reads every archived live run back and records whether an event started
within 6 months, once that is known.

For each file in data/archive/YYYY/*.json (a provisional run is skipped when an official run exists for the same
as-of date and claims week):
  asof, p6, colour       from the run
  outcome_known          the as-of month is at least 6 months before the latest month in triggers_monthly.csv
  during_event           the real-time event state (src/model/realtime_events.py) says an event was already under
                         way in the as-of month; such runs are left out of the counts (the score predicts starts)
  event_started_within_6m  only when outcome_known and not during_event: a provisional start in one of the 6
                         calendar months after the as-of month (only starts count)

Writes data/model/live_scorecard.csv. Run in the refresh workflow after live.py --archive:
    python src/model/live_scorecard.py
"""

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "data" / "model"
ARCHIVE = ROOT / "data" / "archive"
OUT = MODEL / "live_scorecard.csv"

import sys  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import realtime_events as rte  # noqa: E402

COLUMNS = ["asof", "p6", "colour", "during_event", "outcome_known", "event_started_within_6m"]


def read_runs(archive: Path) -> list[dict]:
    """Every archived run (asof, claims week, p6, colour, provisional), provisional duplicates dropped."""
    runs = []
    for f in sorted(archive.glob("*/*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        runs.append({"asof": d["asof"], "week": d["inputs"]["initial_claims_week"], "p6": d["score"]["p6"],
                     "colour": d["score"]["colour"], "provisional": f.name.endswith("_provisional.json")})
    official = {(r["asof"], r["week"]) for r in runs if not r["provisional"]}
    return [r for r in runs if not (r["provisional"] and (r["asof"], r["week"]) in official)]


def scorecard(runs: list[dict], legs: pd.DataFrame) -> pd.DataFrame:
    states = rte.state_by_month(legs)
    latest = legs.index.max()
    starts = set(pd.Timestamp(s + "-01") for s in rte.starts(legs))
    rows = []
    for r in runs:
        m = pd.Timestamp(r["asof"][:7] + "-01")
        known = m + pd.DateOffset(months=6) <= latest
        during = bool(states.under_way.get(m, False))
        started = None
        if known and not during:
            window = [m + pd.DateOffset(months=k) for k in range(1, 7)]
            started = any(w in starts for w in window)
        rows.append({"asof": r["asof"], "p6": r["p6"], "colour": r["colour"], "during_event": during,
                     "outcome_known": known, "event_started_within_6m": started})
    return pd.DataFrame(rows, columns=COLUMNS)


def main() -> None:
    card = scorecard(read_runs(ARCHIVE), rte.month_end_on())
    card.to_csv(OUT, index=False)
    judged = card[card.outcome_known & ~card.during_event]
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(card)} live runs, {len(judged)} old enough to judge")


if __name__ == "__main__":
    main()
