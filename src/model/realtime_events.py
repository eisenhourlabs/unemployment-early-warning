"""
Real-time "event under way" state (review WP4, Part A): one rule, used by live.py (the live flag) and forecast.py
(the forecast tests), so both date events the same way.

A LEG is on at the end of a month when, on data as known then:
  - the Sahm indicator is 0.50 or more (unemployment's 3-month average 0.5 point above its 12-month low), or
  - the initial-claims 4-week average is 25% or more above its lowest 4-week average of the previous 52 weeks.
These are the event's own thresholds (src/model/events.py UR_RISE, CLAIMS_RISE) and equal "red" on confirmation
triggers 1 and 2.

Walk the months in order with a quiet counter: an on-month sets quiet = 0 and starts a new event if quiet was 6 or
more (or there was no earlier on-month); an off-month adds 1. The event is "under way" while quiet < 6.

This is provisional and automatic. The final event list (data/model/events.csv, dated on final data and classified
by Troy) is unchanged and remains the basis for fitting.

Check:  python src/model/realtime_events.py      (prints the starts since 1980 and the agreement with events.csv)
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "data" / "model"

SAHM_ON = 0.50          # = events.py UR_RISE
CLAIMS_ON = 0.25        # = events.py CLAIMS_RISE
QUIET_MONTHS = 6        # off-months needed to end an event


def month_end_on(triggers: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per month (index = month start): columns 'ur' and 'claims' (bool), from data/model/triggers_monthly.csv
    month-end readings (blanks count as off)."""
    t = triggers if triggers is not None else pd.read_csv(MODEL / "triggers_monthly.csv", parse_dates=["month"])
    t = t.set_index("month").sort_index()
    return pd.DataFrame({"ur": t.sahm_value.fillna(-1) >= SAHM_ON,
                         "claims": t.claims_vs_low_value.fillna(-1) >= CLAIMS_ON}, index=t.index)


def leg_name(ur: bool, claims: bool) -> str:
    return "both" if ur and claims else "claims" if claims else "unemployment"


def event_state(legs: pd.DataFrame, current: dict | None = None, until=None) -> dict:
    """The state after the last month of `legs` (or after `until`, a month start, inclusive).

    legs:    DataFrame indexed by month start with bool columns 'ur' and 'claims' (month_end_on()).
    current: this run's reading for the current, unfinished month {'ur': bool, 'claims': bool, 'month': Timestamp};
             it replaces / adds that month.
    Returns {"under_way", "provisional_start" ("YYYY-MM" or None), "months_since_start" (start month = 1; 0 if not
    under way), "leg" ("claims" / "unemployment" / "both" at the start, or None), "last_on" ("YYYY-MM" or None)}."""
    legs = legs.copy()
    if until is not None:
        legs = legs[legs.index <= pd.Timestamp(until)]
    if current is not None:
        m = pd.Timestamp(current["month"])
        legs = legs[legs.index < m]
        legs.loc[m] = [bool(current["ur"]), bool(current["claims"])]
    quiet, start, start_leg, last_on = None, None, None, None
    for month, r in legs.iterrows():
        if r.ur or r.claims:
            if quiet is None or quiet >= QUIET_MONTHS:
                start, start_leg = month, leg_name(r.ur, r.claims)
            quiet, last_on = 0, month
        elif quiet is not None:
            quiet += 1
    under_way = quiet is not None and quiet < QUIET_MONTHS
    last = legs.index[-1] if len(legs) else None
    since = ((last.year - start.year) * 12 + last.month - start.month + 1) if under_way else 0
    return {"under_way": bool(under_way), "provisional_start": f"{start:%Y-%m}" if under_way else None,
            "months_since_start": int(since), "leg": start_leg if under_way else None,
            "last_on": f"{last_on:%Y-%m}" if last_on is not None else None}


def state_by_month(legs: pd.DataFrame) -> pd.DataFrame:
    """The state at the end of every month (for the forecast tests and the scorecard): columns under_way (bool),
    start (Timestamp or NaT)."""
    rows, quiet, start = [], None, None
    for month, r in legs.sort_index().iterrows():
        if r.ur or r.claims:
            if quiet is None or quiet >= QUIET_MONTHS:
                start = month
            quiet = 0
        elif quiet is not None:
            quiet += 1
        on = quiet is not None and quiet < QUIET_MONTHS
        rows.append({"month": month, "under_way": on, "start": start if on else pd.NaT})
    return pd.DataFrame(rows).set_index("month")


def starts(legs: pd.DataFrame) -> list[str]:
    s = state_by_month(legs)
    first = s.under_way & ~s.under_way.shift(1, fill_value=False)
    return [f"{m:%Y-%m}" for m in s.index[first]]


def main() -> None:
    legs = month_end_on()
    s = state_by_month(legs)
    ev = pd.read_csv(MODEL / "events.csv", dtype={"start_month": str, "end_month": str})
    final = pd.Series(False, index=s.index)
    for e in ev.itertuples():
        end = s.index[-1] if e.end_month == "ongoing" else pd.Timestamp(e.end_month + "-01")
        final |= (s.index >= pd.Timestamp(e.start_month + "-01")) & (s.index <= end)
    w = s.index >= "1980-01-01"
    agree = (s.under_way[w] == final[w]).mean()
    print(f"1980-{s.index[-1]:%Y-%m}: {w.sum()} months, real-time state agrees with events.csv in "
          f"{(s.under_way[w] == final[w]).sum()} ({agree:.1%})")
    print("Provisional starts since 1980:", [x for x in starts(legs) if x >= "1980"])
    print("Now:", event_state(legs))


if __name__ == "__main__":
    main()
