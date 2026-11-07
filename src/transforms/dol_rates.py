"""
Rates derived from DOL data. Rebuilt in full on every run, so revised inputs flow through automatically.

1. Weekly claims rates (from data/processed/dol/national_weekly.csv), in percent of covered employment:
     ic_rate_sa  = initial claims SA   / covered employment x 100
     cc_rate_sa  = continued claims SA / covered employment x 100   (compare: DOL's IUR SA)
   plus NSA versions and 4-week averages (mean of the last 4 weekly rates).
   -> data/processed/dol/claims_rates_weekly.csv

2. Monthly exhaustion rate and average duration (from ar5159.csv), by state and for the US.
   Definitions follow DOL's "Glossary of Data Definitions" and reproduce DOL's published figures:
     exhaustion_rate_12m = average monthly final payments, 12 months ending this month
                           / average monthly first payments, 12 months ending 6 months earlier x 100
     avg_duration_12m    = weeks compensated (all weeks), 12 months / first payments, 12 months
   The US row is the sum of all areas, only for months where every area has reported.
   -> data/processed/dol/exhaustion_duration_monthly.csv

3. Quarterly potential and exhaustee duration (from ar218.csv), by state and US (weighted averages).
   -> data/processed/dol/benefit_duration_quarterly.csv

Run:  python src/transforms/dol_rates.py
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DOL_DIR = ROOT / "data" / "processed" / "dol"


def claims_rates() -> pd.DataFrame:
    w = pd.read_csv(DOL_DIR / "national_weekly.csv")
    out = w[["week_ended", "source_initial", "source_continued", "covered_employment"]].copy()
    for kind, sa, nsa in [("ic", "ic_sa", "ic_nsa"), ("cc", "cc_sa", "cc_nsa")]:
        out[f"{kind}_rate_sa"] = w[sa] / w.covered_employment * 100
        out[f"{kind}_rate_nsa"] = w[nsa] / w.covered_employment * 100
        out[f"{kind}_rate_sa_4wk"] = out[f"{kind}_rate_sa"].rolling(4, min_periods=4).mean()
        out[f"{kind}_rate_nsa_4wk"] = out[f"{kind}_rate_nsa"].rolling(4, min_periods=4).mean()
    out["iur_sa_published"] = w.iur_sa      # DOL's own rate, for comparison
    rate_cols = [c for c in out.columns if "_rate_" in c]
    out[rate_cols] = out[rate_cols].round(4)
    return out


def full_months(df: pd.DataFrame) -> pd.DataFrame:
    """Reindex one state's monthly rows to a complete month sequence, so 12-month windows are exact."""
    df = df.set_index(pd.to_datetime(df.month_ended)).sort_index()
    months = pd.date_range(df.index.min(), df.index.max(), freq="ME")
    return df.reindex(months)


def exhaustion_duration() -> pd.DataFrame:
    m = pd.read_csv(DOL_DIR / "ar5159.csv", low_memory=False)
    cols = {"fp_state_ui_total": "first_payments", "final_payments_state_ui": "final_payments",
            "wc_state_ui_total": "weeks_compensated"}
    m = m[["state", "month_ended", *cols]].rename(columns=cols)

    # US = sum of all areas, only for months where every area reported.
    counts = m.groupby("month_ended").state.count()
    complete = counts[counts >= counts.max()].index
    us = m[m.month_ended.isin(complete)].groupby("month_ended")[list(cols.values())].sum().reset_index()
    us["state"] = "US"

    results = []
    for state, df in pd.concat([m, us]).groupby("state"):
        df = full_months(df)
        fp12 = df.first_payments.rolling(12, min_periods=12).mean()
        out = pd.DataFrame({
            "state": state,
            "month_ended": df.index.strftime("%Y-%m-%d"),
            "first_payments": df.first_payments,
            "final_payments": df.final_payments,
            "weeks_compensated": df.weeks_compensated,
            "exhaustion_rate_12m": (df.final_payments.rolling(12, min_periods=12).mean() / fp12.shift(6) * 100),
            "avg_duration_12m": (df.weeks_compensated.rolling(12, min_periods=12).sum()
                                 / df.first_payments.rolling(12, min_periods=12).sum()),
        })
        results.append(out.dropna(subset=["first_payments"]))
    out = pd.concat(results, ignore_index=True)
    out[["exhaustion_rate_12m", "avg_duration_12m"]] = out[["exhaustion_rate_12m", "avg_duration_12m"]].round(2)
    for c in cols.values():
        out[c] = out[c].round().astype("Int64")
    return out


def quarterly_duration() -> pd.DataFrame:
    q = pd.read_csv(DOL_DIR / "ar218.csv")
    keep = ["state", "quarter_ended", "potential_total", "potential_avg_weeks", "actual_total", "actual_avg_weeks"]
    q = q[keep]
    counts = q.groupby("quarter_ended").state.count()
    complete = counts[counts >= counts.max()].index
    qq = q[q.quarter_ended.isin(complete)].copy()
    qq["p_x"] = qq.potential_avg_weeks * qq.potential_total
    qq["a_x"] = qq.actual_avg_weeks * qq.actual_total
    us = qq.groupby("quarter_ended")[["potential_total", "p_x", "actual_total", "a_x"]].sum()
    us["potential_avg_weeks"] = (us.p_x / us.potential_total).round(2)
    us["actual_avg_weeks"] = (us.a_x / us.actual_total).round(2)
    us = us.reset_index().assign(state="US")[keep]
    return pd.concat([q, us], ignore_index=True).sort_values(["state", "quarter_ended"])


def main() -> int:
    outputs = {
        "claims_rates_weekly.csv": claims_rates(),
        "exhaustion_duration_monthly.csv": exhaustion_duration(),
        "benefit_duration_quarterly.csv": quarterly_duration(),
    }
    for name, df in outputs.items():
        df.to_csv(DOL_DIR / name, index=False)
        print(f"{name}: {len(df)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
