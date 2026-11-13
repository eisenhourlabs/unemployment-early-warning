"""
Labour flows (review WP5, Part D): three monthly duration measures for the Duration page.

  job_finding_rate          Shimer's job-finding rate, percent: F(t+1) = 1 - [U(t+1) - S(t+1)] / U(t), dated t+1,
                            with U = unemployed (UNEMPLOY) and S = unemployed less than 5 weeks (UEMPLT5), thousands.
                            "Leaving unemployment" includes leaving the labour force. Blank when U(t), U(t+1) or
                            S(t+1) is missing (no October 2025 survey).
  job_finding_rate_3m       its 3-month average (blank if any of the 3 months is blank)
  vacancies_per_unemployed  JOLTS job openings (JTSJOL) / UNEMPLOY, from December 2000
  cc_per_new_claim          4-week average of SA continuing claims / average weekly SA initial claims of the 26 weeks
                            ending one week earlier, at the last week ending in each month

Inputs: data/processed/UNEMPLOY.csv, UEMPLT5.csv, JTSJOL.csv, CCSA.csv, ICSA.csv (FRED).
Output: data/processed/labor_flows_monthly.csv
Run:    python src/transforms/labor_flows.py      (refresh workflow, after state_measures.py)
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
OUT = PROCESSED / "labor_flows_monthly.csv"


def fred_monthly(series_id: str) -> pd.Series:
    s = pd.read_csv(PROCESSED / f"{series_id}.csv", parse_dates=["date"]).set_index("date")["value"]
    return s.asfreq("MS")          # a missing month becomes a blank row


def job_finding(u: pd.Series, s: pd.Series) -> pd.Series:
    """F(t+1) = 1 - (U(t+1) - S(t+1)) / U(t), percent, dated t+1 (blank where any input is blank)."""
    return 100 * (1 - (u - s) / u.shift(1))


def cc_per_new_claim(weekly: pd.DataFrame) -> pd.Series:
    """Monthly: CCSA 4-week mean / mean ICSA over the 26 weeks ending one week earlier (last week in the month)."""
    w = weekly.set_index("week_ended").sort_index()
    ratio = w.CCSA.rolling(4).mean() / w.ICSA.rolling(26).mean().shift(1)
    m = ratio.dropna().groupby(ratio.dropna().index.to_period("M")).last()
    m.index = m.index.to_timestamp()
    return m


def build() -> pd.DataFrame:
    u, s, jol = fred_monthly("UNEMPLOY"), fred_monthly("UEMPLT5"), fred_monthly("JTSJOL")
    f = job_finding(u, s.reindex(u.index))
    out = pd.DataFrame({"job_finding_rate": f})
    out["job_finding_rate_3m"] = f.rolling(3).mean()           # rolling(3) leaves blanks around a missing month
    out["vacancies_per_unemployed"] = (jol / u.reindex(jol.index)).reindex(out.index)
    # The FRED claims files (the same figures as data/model/claims_weekly.csv, which the refresh rebuilds only later)
    weekly = pd.DataFrame({k: pd.read_csv(PROCESSED / f"{k}.csv", parse_dates=["date"]).set_index("date")["value"]
                           for k in ("CCSA", "ICSA")}).rename_axis("week_ended").reset_index()
    out = out.join(cc_per_new_claim(weekly).rename("cc_per_new_claim"), how="outer")
    out = out.dropna(how="all")
    out.index.name = "month"
    return out


def main() -> None:
    out = build().round(4)
    out.index = out.index.strftime("%Y-%m-%d")
    out.to_csv(OUT)
    last = out.dropna(subset=["job_finding_rate_3m"]).iloc[-1]
    print(f"Wrote {OUT} ({len(out)} months). Latest job-finding rate (3m) {last.job_finding_rate_3m:.1f}%, "
          f"openings per unemployed {out.vacancies_per_unemployed.dropna().iloc[-1]:.2f}, "
          f"continuing claims per new claim {out.cc_per_new_claim.dropna().iloc[-1]:.1f}")


if __name__ == "__main__":
    main()
