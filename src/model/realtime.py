"""
Real-time data: what a series said on a given past date.

The one function other scripts need:

    from realtime import as_known_on
    ur = as_known_on("UNRATE", "2008-10-15")    # the unemployment rate as published on 15 Oct 2008

It returns a pandas Series indexed by observation date, holding only the values that had been published
by that date, at the values they had then (before later revisions). Publication lags are respected
automatically: a month that had not been released by the date is simply not there.

How it decides, per row of config/model_series.csv:
  * vintage_source = alfred: uses data/model/alfred/<ID>.csv (from alfred_fetcher.py). A row of that file
    is "in force" on date D when realtime_start <= D <= realtime_end.
    Before the series' first ALFRED vintage there is nothing truly real-time, so it uses the earliest
    vintage, keeps only observations at least release_lag_days old, and marks the result not real-time
    (decision 2026-11-08: TEMPHELPS before 2011, JOLTS before 2010, PERMIT before 1999).
  * vintage_source = current: uses today's figures (DOL claims, our rule) and keeps only observations at
    least release_lag_days old by date D.

The result carries two notes in result.attrs:
    attrs["real_time"]  True if these are the values published at the time, False otherwise
    attrs["source"]     "alfred", "alfred-earliest" (before the first vintage) or "current"

Run this file to check it against FRED's own real-time Sahm indicator (SAHMREALTIME):
    python src/model/realtime.py
"""

from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "model_series.csv"
ALFRED_DIR = ROOT / "data" / "model" / "alfred"
CLAIMS = ROOT / "data" / "model" / "claims_weekly.csv"
PROCESSED = ROOT / "data" / "processed"


@lru_cache(maxsize=None)        # read each file only once per run
def _config() -> pd.DataFrame:
    return pd.read_csv(CONFIG, comment="#").set_index("series_id")


@lru_cache(maxsize=None)
def _alfred(series_id: str) -> pd.DataFrame:
    # Dates stay as text ("YYYY-MM-DD"): text in this form sorts and compares like dates, and it avoids
    # problems with FRED's "9999-12-31" (too far in the future for pandas dates).
    return pd.read_csv(ALFRED_DIR / f"{series_id}.csv", dtype={"date": str, "realtime_start": str,
                                                                 "realtime_end": str})


@lru_cache(maxsize=None)
def _current(series_id: str) -> pd.Series:
    """Today's figures: from the claims table if the column is there, otherwise data/processed/<ID>.csv."""
    claims = pd.read_csv(CLAIMS, parse_dates=["week_ended"]).set_index("week_ended")
    if series_id in claims.columns:
        return claims[series_id].dropna()
    df = pd.read_csv(PROCESSED / f"{series_id}.csv", parse_dates=["date"])
    return df.set_index("date")["value"]


def as_known_on(series_id: str, as_of) -> pd.Series:
    """Return series_id as it was published on date `as_of` (see the notes at the top of this file)."""
    d = pd.Timestamp(as_of)
    cfg = _config().loc[series_id]
    lag = pd.Timedelta(days=int(cfg.release_lag_days))

    if cfg.vintage_source == "alfred":
        df = _alfred(series_id)
        d_text = d.strftime("%Y-%m-%d")
        first_vintage = df.realtime_start.min()
        if d_text >= first_vintage:
            # Normal case: the rows that were the published values on date D.
            rows = df[(df.realtime_start <= d_text) & (df.realtime_end >= d_text)]
            out = pd.Series(rows.value.values, index=pd.to_datetime(rows.date), name=series_id)
            out.attrs.update(real_time=True, source="alfred")
        else:
            # Before ALFRED's archive starts: earliest vintage, cut back by the usual publication lag.
            rows = df[(df.realtime_start <= first_vintage) & (df.realtime_end >= first_vintage)]
            out = pd.Series(rows.value.values, index=pd.to_datetime(rows.date), name=series_id)
            out = out[out.index + lag <= d]
            out.attrs.update(real_time=False, source="alfred-earliest")
    else:
        full = _current(series_id)
        out = full[full.index + lag <= d].rename(series_id)
        out.attrs.update(real_time=False, source="current")
    return out.sort_index()


# ---------------------------------------------------------------------------------------------------
# Check: rebuild the real-time Sahm indicator from the UNRATE vintages and compare with SAHMREALTIME.
# ---------------------------------------------------------------------------------------------------
def sahm(ur: pd.Series) -> float:
    """Sahm indicator for the last month of `ur`: its 3-month average minus the lowest 3-month average
    of the previous 12 months."""
    avg3 = ur.rolling(3, min_periods=2).mean()     # 2 of 3 months allowed (e.g. October 2025 missing)
    return avg3.iloc[-1] - avg3.iloc[-13:-1].min()


def check_against_sahmrealtime() -> pd.DataFrame:
    alfred = _alfred("UNRATE")
    # Release date of each month = the first day its value appears in ALFRED.
    release = alfred.groupby("date").realtime_start.min()
    release = release[release.index > alfred.realtime_start.min()]   # months released after the archive began
    rows = []
    for month, released_on in release.items():
        ur = as_known_on("UNRATE", released_on).dropna()
        ur = ur[ur.index <= month]                 # the vintage as of the release of `month`
        rows.append({"date": pd.Timestamp(month), "ours": round(sahm(ur), 2)})
    ours = pd.DataFrame(rows).set_index("date")
    fred = pd.read_csv(PROCESSED / "SAHMREALTIME.csv", parse_dates=["date"]).set_index("date")["value"]
    both = ours.join(fred.rename("fred"), how="inner").dropna()
    both["diff"] = (both.ours - both.fred).round(2)
    return both


if __name__ == "__main__":
    both = check_against_sahmrealtime()
    exact = (both["diff"].abs() < 0.005).mean()
    within = (both["diff"].abs() <= 0.05).mean()
    print(f"Real-time Sahm indicator rebuilt from UNRATE vintages vs. FRED SAHMREALTIME, "
          f"{both.index[0]:%Y-%m} to {both.index[-1]:%Y-%m} ({len(both)} months):")
    print(f"  identical (to 0.01): {exact:.1%}   within 0.05 pt: {within:.1%}   "
          f"largest difference: {both['diff'].abs().max():.2f} pt")
    print("  Largest differences:")
    print(both.reindex(both["diff"].abs().sort_values(ascending=False).index).head(8).to_string())

    # A few spot checks a reader can verify by hand on ALFRED.
    for sid, d in [("UNRATE", "2008-10-15"), ("TEMPHELPS", "2007-06-30"), ("ICSA", "2008-10-09")]:
        s = as_known_on(sid, d)
        print(f"{sid} as known on {d}: last observation {s.index[-1]:%Y-%m-%d} = {s.iloc[-1]}  "
              f"(source {s.attrs['source']}, real-time {s.attrs['real_time']})")
