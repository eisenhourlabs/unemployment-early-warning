"""
Duration watch backtest (review WP5, Part A): how often each band of "continuing claims vs. a year ago" has been
followed, within 12 months, by a sharp lengthening of unemployment durations.

Reads only (no model is fitted). For each month since 1968:
  cc_yoy = 4-week average of SA continuing claims (CCSA, last week ending in the month) / the same 12 months
           earlier - 1  (the value behind confirmation trigger 4; amber +10%, red +20%)
  band   = falling (< 0), green (0 to < +10%), amber (+10% to < +20%), red (+20% or more)
Outcomes at month t (blank when month t+12 is not observed yet):
  lt_share_up    share of unemployed out of work 27+ weeks (LNS13025703) up 3.0 points or more
  median_up      median weeks unemployed (UEMPMED) up 1.5 weeks or more
  duration_up    DOL average benefit duration, 12 months (US), up 0.75 week or more   (from 1996)
  exhaustion_up  DOL exhaustion rate, 12 months (US), up 3.0 points or more           (from 1996)
Months 2019-04 to 2021-12 are left out everywhere (the pandemic).
Limits: today's revised data, in sample, overlapping months (about 20 separate episodes for the household-survey
outcomes and only 3 to 4 for the DOL ones). Descriptive, not a forecast.

Writes data/model/severity_watch.csv (outcome, band, months, share_followed; plus a base_rate row per outcome) and
data/model/severity_watch_monthly.csv (month, cc_yoy, band). Prints the AUC screen of WP5 Part D step 5.

Run:  python src/model/severity_watch.py      (January re-fit chain, after triggers.py)
"""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "data" / "model"
PROCESSED = ROOT / "data" / "processed"

START = "1968-01-01"
EXCLUDE = ("2019-04-01", "2021-12-01")
BANDS = ["falling", "green", "amber", "red"]
OUTCOMES = {  # name: (series, rise needed within 12 months)
    "lt_share_up": ("lt_share", 3.0),
    "median_up": ("median_weeks", 1.5),
    "duration_up": ("avg_duration_12m", 0.75),
    "exhaustion_up": ("exhaustion_rate_12m", 3.0),
}


def band_of(v: float) -> str | None:
    """The Duration watch band of a cc_yoy value (same rule as src/site/common.py duration_watch)."""
    if pd.isna(v):
        return None
    return "falling" if v < 0 else "green" if v < 0.10 else "amber" if v < 0.20 else "red"


def monthly_cc_yoy(weekly: pd.DataFrame) -> pd.Series:
    """cc_yoy by month from a weekly table with columns week_ended, CCSA: last week ending in each month."""
    w = weekly.dropna(subset=["CCSA"]).set_index("week_ended")["CCSA"].sort_index()
    cc4 = w.rolling(4).mean()
    by_month = cc4.groupby(cc4.index.to_period("M")).last()
    by_month.index = by_month.index.to_timestamp()
    return by_month / by_month.shift(12) - 1


def fred_monthly(series_id: str) -> pd.Series:
    """A monthly FRED file, with a single missing month (October 2025) filled by linear interpolation."""
    s = pd.read_csv(PROCESSED / f"{series_id}.csv", parse_dates=["date"]).set_index("date")["value"]
    s = s.asfreq("MS")
    return s.interpolate(limit=1, limit_area="inside")


def outcomes_frame(levels: pd.DataFrame) -> pd.DataFrame:
    """True / False / blank outcome columns from the level columns (blank when t+12 is not observed)."""
    out = pd.DataFrame(index=levels.index)
    for name, (col, rise) in OUTCOMES.items():
        ahead = levels[col].shift(-12) - levels[col]
        out[name] = (ahead >= rise).where(ahead.notna())
    return out


def build_frame() -> pd.DataFrame:
    weekly = pd.read_csv(MODEL / "claims_weekly.csv", parse_dates=["week_ended"])
    cc_yoy = monthly_cc_yoy(weekly)
    dol = pd.read_csv(PROCESSED / "dol" / "exhaustion_duration_monthly.csv", parse_dates=["month_ended"])
    dol = dol[dol.state == "US"].copy()
    dol["month"] = dol.month_ended.dt.to_period("M").dt.to_timestamp()
    dol = dol.set_index("month")[["avg_duration_12m", "exhaustion_rate_12m"]]
    idx = pd.date_range(START, cc_yoy.index.max(), freq="MS")
    levels = pd.DataFrame({"lt_share": fred_monthly("LNS13025703"), "median_weeks": fred_monthly("UEMPMED")}).reindex(idx)
    levels = levels.join(dol.reindex(idx))
    f = pd.DataFrame({"cc_yoy": cc_yoy.reindex(idx)}, index=idx)
    f["band"] = f.cc_yoy.map(band_of)
    f = f.join(outcomes_frame(levels))
    f["excluded"] = (f.index >= EXCLUDE[0]) & (f.index <= EXCLUDE[1])
    return f


def summary(f: pd.DataFrame) -> pd.DataFrame:
    use = f[~f.excluded & f.band.notna()]
    rows = []
    for outcome in OUTCOMES:
        o = use.dropna(subset=[outcome])
        for band in BANDS:
            b = o[o.band == band]
            rows.append({"outcome": outcome, "band": band, "months": len(b),
                         "share_followed": round(float(b[outcome].astype(float).mean()), 4) if len(b) else None})
        rows.append({"outcome": outcome, "band": "base_rate", "months": len(o),
                     "share_followed": round(float(o[outcome].astype(float).mean()), 4)})
    return pd.DataFrame(rows)


def auc(score: pd.Series, outcome: pd.Series) -> float:
    """Area under the ROC curve (probability a month with the outcome scores higher than one without; ties 1/2)."""
    d = pd.DataFrame({"s": score, "y": outcome}).dropna()
    ranks = d.s.rank()
    pos = d.y.astype(bool)
    n1, n0 = pos.sum(), (~pos).sum()
    return float((ranks[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def screen(f: pd.DataFrame) -> None:
    """WP5 Part D step 5: AUC of the labour-flow measures beside cc_yoy (printed, recorded in docs/model.md)."""
    path = PROCESSED / "labor_flows_monthly.csv"
    if not path.exists():
        print("  (labor_flows_monthly.csv not found: run src/transforms/labor_flows.py for the AUC screen)")
        return
    flows = pd.read_csv(path, parse_dates=["month"]).set_index("month")
    use = f[~f.excluded].join(flows)
    cands = {"cc_yoy": use.cc_yoy,
             "minus 12-month change in job-finding rate (3m)": -(use.job_finding_rate_3m - use.job_finding_rate_3m.shift(12)),
             "minus 12-month % change in openings per unemployed": -(use.vacancies_per_unemployed
                                                                     / use.vacancies_per_unemployed.shift(12) - 1)}
    for outcome in ("lt_share_up", "median_up"):
        print(f"  AUC for {outcome}:")
        for name, s in cands.items():
            print(f"    {auc(s, use[outcome]):.2f}  {name}")


def main() -> None:
    f = build_frame()
    table = summary(f)
    table.to_csv(MODEL / "severity_watch.csv", index=False)
    monthly = f[["cc_yoy", "band"]].dropna().reset_index().rename(columns={"index": "month"})
    monthly["month"] = monthly.month.dt.strftime("%Y-%m")
    monthly["cc_yoy"] = monthly.cc_yoy.round(4)
    monthly.to_csv(MODEL / "severity_watch_monthly.csv", index=False)
    print(table.pivot(index="band", columns="outcome", values="share_followed").round(2).to_string())
    print(table.pivot(index="band", columns="outcome", values="months").to_string())
    print(f"Latest: {monthly.month.iloc[-1]} cc_yoy {monthly.cc_yoy.iloc[-1]:+.3f} ({monthly.band.iloc[-1]})")
    screen(f)
    print(f"Wrote {MODEL / 'severity_watch.csv'} and severity_watch_monthly.csv")


if __name__ == "__main__":
    main()
