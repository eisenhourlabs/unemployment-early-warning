"""
Labor-market deterioration events since 1967 (Phase 3 plan, decision 1), measured on today's final data.

An event STARTS in the first month that either leg is "on":
  * Unemployment leg (monthly): the unemployment rate's 3-month average is at least 0.5 point above
    the lowest 3-month average of the prior 12 months (months t-12 to t-1; the Sahm-rule shape).
  * Claims leg (weekly): the SA initial claims 4-week average (IC4WSA) is at least 25% above its lowest
    value of the prior 52 weeks (not counting the current week). A month's claims leg is on if any
    week ending in that month is on. Needs 52 weeks of history, so it can be tested from early 1968.

An event ENDS once both legs have been off for QUIET_MONTHS (6) months in a row; its end month is the
last month a leg was on. A new event cannot start until the previous one has ended, so those quiet
months are also the minimum gap between events (decision 2026-11-08).

Writes:
  data/model/event_flags_monthly.csv   each month: both legs' values, on/off, and the event it belongs to
  data/model/events.csv                one row per event (the list for Troy's sign-off)
and prints how the list changes with 3 and 12 quiet months (sensitivity check).

Run it (after build_claims_history.py):
    python src/model/events.py
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
MODEL = ROOT / "data" / "model"
NOTES = ROOT / "config" / "event_notes.csv"

UR_RISE = 0.5          # unemployment leg: points above the prior 12-month low of the 3-month average
CLAIMS_RISE = 0.25     # claims leg: 25% above the prior 52-week low
QUIET_MONTHS = 6       # both legs off this many months in a row = event over
FIRST_MONTH = "1967-01-01"
PEAK_WINDOW_AFTER_END = 12   # months after the end still searched for the peak ...
PEAK_STOP_BEFORE_NEXT = 6    # ... but stopping this many months before the next event's start
EXCLUDE_FROM_FIT = {2020}    # decision 4: evaluate on 2020, but don't let it set thresholds or weights


# ---------------------------------------------------------------------------------------------------
# The two legs
# ---------------------------------------------------------------------------------------------------
def unemployment_leg() -> pd.DataFrame:
    ur = pd.read_csv(PROCESSED / "UNRATE.csv", parse_dates=["date"]).set_index("date")["value"]
    ur = ur.asfreq("MS")                              # one row per month; a missing month stays blank
    avg3 = ur.rolling(3, min_periods=2).mean()        # October 2025 is missing: average the other two
    low12 = avg3.shift(1).rolling(12, min_periods=12).min()   # lowest of months t-12 .. t-1
    gap = (avg3 - low12).round(6)                     # round so 0.5 isn't missed by a tiny float error
    return pd.DataFrame({"unrate": ur, "ur_3mo_avg": avg3.round(3), "ur_gap": gap.round(3),
                         "ur_on": gap >= UR_RISE})


def claims_leg() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (weekly table, monthly summary)."""
    w = pd.read_csv(MODEL / "claims_weekly.csv", parse_dates=["week_ended"]).set_index("week_ended")
    ic4 = w["IC4WSA"].astype(float)
    low52 = ic4.shift(1).rolling(52, min_periods=52).min()     # lowest of the previous 52 weeks
    rise = (ic4 / low52 - 1).round(6)
    weekly = pd.DataFrame({"ic4wsa": ic4, "ic4wsa_low52": low52, "claims_rise": rise,
                           "claims_on": rise >= CLAIMS_RISE})
    weekly = weekly[low52.notna()]                             # weeks where the leg can be tested
    # Month of each week = month of its Saturday end date. Keep the largest rise in the month.
    month = weekly.index.to_period("M").to_timestamp()
    monthly = weekly.groupby(month).agg(claims_rise_max=("claims_rise", "max"),
                                        claims_on=("claims_on", "any"))
    return weekly, monthly


# ---------------------------------------------------------------------------------------------------
# Turning on/off months into events
# ---------------------------------------------------------------------------------------------------
def find_events(on: pd.Series, quiet_months: int) -> list[tuple]:
    """Walk month by month. Returns [(start, end or None if still going), ...]."""
    events, start, last_on, quiet = [], None, None, 0
    for month, is_on in on.items():
        if start is None:                 # not in an event: wait for a leg to switch on
            if is_on:
                start, last_on, quiet = month, month, 0
        elif is_on:                       # in an event, a leg still on: reset the quiet count
            last_on, quiet = month, 0
        else:                             # in an event, both legs off
            quiet += 1
            if quiet >= quiet_months:
                events.append((start, last_on))
                start = None
    if start is not None:
        events.append((start, None))      # still going at the end of the data
    return events


def nber_recessions() -> list[tuple]:
    """NBER recessions as (peak month, last recession month). FRED's USREC = 1 from the month after the
    peak through the trough month."""
    rec = pd.read_csv(PROCESSED / "USREC.csv", parse_dates=["date"]).set_index("date")["value"]
    rec = rec[rec.index >= "1960-01-01"]
    starts = rec[(rec == 1) & (rec.shift(1) == 0)].index
    ends = rec[(rec == 1) & (rec.shift(-1) == 0)].index
    return [(s - pd.DateOffset(months=1), e) for s, e in zip(starts, ends)]


def months_between(a, b) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def describe(events, flags, weekly, recessions) -> pd.DataFrame:
    """One row per event with the measures Troy asked for."""
    notes = pd.read_csv(NOTES, dtype=str).set_index("start_month")["note"] if NOTES.exists() else {}
    last_month = flags.index[-1]
    rows = []
    for i, (start, end) in enumerate(events):
        stop = end if end is not None else last_month
        window = flags.loc[start:stop]

        # Which leg came first, and when the other one followed (within the event).
        ur_first = window.index[window.ur_on][0] if window.ur_on.any() else None
        cl_first = window.index[window.claims_on][0] if window.claims_on.any() else None
        if ur_first == start and cl_first == start:
            first_leg = "both"
        else:
            first_leg = "unemployment" if ur_first == start else "claims"
        other = cl_first if first_leg == "unemployment" else ur_first
        if first_leg == "both":
            other_timing = "same month"
        elif other is None:
            other_timing = "did not trigger"
        else:
            other_timing = f"+{months_between(start, other)} months ({other:%Y-%m})"
        cl_weeks = weekly.loc[start:stop + pd.offsets.MonthEnd(0)]
        first_claims_week = cl_weeks.index[cl_weeks.claims_on][0] if cl_weeks.claims_on.any() else None

        # Peak rise, searched from the start to 12 months after the end, but stopping 6 months before the
        # next event starts, so the run-up to the next downturn isn't credited to this one.
        search_end = stop + pd.DateOffset(months=PEAK_WINDOW_AFTER_END)
        if i + 1 < len(events):
            search_end = min(search_end, events[i + 1][0] - pd.DateOffset(months=PEAK_STOP_BEFORE_NEXT))
        search_end = max(search_end, stop)       # but always search the event itself
        ur = flags.unrate
        ur_base = ur.loc[start - pd.DateOffset(months=12):start - pd.DateOffset(months=1)].min()
        ur_peak_month = ur.loc[start:search_end].idxmax()
        ic4 = weekly.ic4wsa
        ic_base = ic4.loc[start - pd.DateOffset(weeks=52):start - pd.Timedelta(days=1)].min()
        ic_peak_week = ic4.loc[start:search_end + pd.offsets.MonthEnd(0)].idxmax()

        # NBER: recession months inside the event, and the nearest recession peak.
        rec_months = sum(max(0, months_between(max(start, p + pd.DateOffset(months=1)), min(stop, t)) + 1)
                         for p, t in recessions)
        near = [(p, t) for p, t in recessions
                if p - pd.DateOffset(months=6) <= stop and t + pd.DateOffset(months=6) >= start]
        if near:
            peak, trough = near[0]
            nber = f"{peak:%Y-%m} peak to {trough:%Y-%m}"
            vs_peak = months_between(peak, start)
        else:
            nber, vs_peak = "none", None

        key = f"{start:%Y-%m}"
        rows.append({
            "event": i + 1,
            "start_month": key,
            "end_month": f"{end:%Y-%m}" if end is not None else "ongoing",
            "length_months": months_between(start, stop) + 1,
            "first_leg": first_leg,
            "other_leg_timing": other_timing,
            "first_claims_week": f"{first_claims_week:%Y-%m-%d}" if first_claims_week is not None else "",
            "ur_low_before": ur_base,
            "ur_peak": ur.loc[ur_peak_month],
            "ur_peak_month": f"{ur_peak_month:%Y-%m}",
            "ur_peak_rise_pt": round(ur.loc[ur_peak_month] - ur_base, 1),
            "ic4wsa_low_before": int(ic_base),
            "ic4wsa_peak": int(ic4.loc[ic_peak_week]),
            "ic4wsa_peak_week": f"{ic_peak_week:%Y-%m-%d}",
            "ic4wsa_peak_rise_pct": round(100 * (ic4.loc[ic_peak_week] / ic_base - 1), 1),
            "nber_recession": nber,
            "nber_months_in_event": rec_months,
            "start_vs_nber_peak_months": vs_peak,
            "scare": not near,            # no NBER recession within 6 months of the event
            "exclude_from_fit": start.year in EXCLUDE_FROM_FIT,
            "note": notes.get(key, "") if len(notes) else "",
        })
    return pd.DataFrame(rows)


def main() -> None:
    ur = unemployment_leg()
    weekly, cl_monthly = claims_leg()
    flags = ur.join(cl_monthly, how="left")
    flags = flags[flags.index >= FIRST_MONTH]
    flags["claims_on"] = flags["claims_on"].fillna(False).astype(bool)   # untestable months count as off
    flags["either_on"] = flags.ur_on | flags.claims_on
    recessions = nber_recessions()

    events = find_events(flags.either_on, QUIET_MONTHS)
    table = describe(events, flags, weekly, recessions)

    # Label each month with its event number (blank outside events).
    flags["event"] = pd.NA
    for row, (start, end) in zip(table.itertuples(), events):
        flags.loc[start:(end if end is not None else flags.index[-1]), "event"] = row.event
    flags["usrec"] = pd.read_csv(PROCESSED / "USREC.csv", parse_dates=["date"]).set_index("date")["value"]

    MODEL.mkdir(parents=True, exist_ok=True)
    flags.to_csv(MODEL / "event_flags_monthly.csv", date_format="%Y-%m-%d", index_label="month")
    table.to_csv(MODEL / "events.csv", index=False)
    weekly.to_csv(MODEL / "claims_leg_weekly.csv", date_format="%Y-%m-%d", index_label="week_ended")

    pd.set_option("display.width", 250)
    print(f"{len(table)} events with {QUIET_MONTHS} quiet months:")
    print(table.drop(columns=["note", "ic4wsa_low_before", "ur_low_before"]).to_string(index=False))

    # Sensitivity: how does the list change with a shorter or longer quiet period?
    for q in (3, 12):
        alt = find_events(flags.either_on, q)
        print(f"\nWith {q} quiet months: {len(alt)} events, starts "
              + ", ".join(f"{s:%Y-%m}" for s, _ in alt))


if __name__ == "__main__":
    main()
