"""
Inputs for the early-warning score (stage 3c): one row per month, each column a candidate indicator as a
continuous value, SIGNED SO THAT HIGHER MEANS WORSE, using only what was published by the month's last day.

Columns (data/model/features_monthly.csv):
  sahm          Sahm indicator (points)                                            higher = worse
  claims_low    SA initial claims 4-wk avg vs. its 52-week low (ratio - 1)          higher = worse
  claims_yoy    SA initial claims 4-wk avg vs. a year ago                           higher = worse
  cont_yoy      SA continued claims (4-wk avg) vs. a year ago                       higher = worse
  temp_help     MINUS the 6-month % change in temp help jobs                        (a fall = positive)
  yield_curve   MINUS the lowest monthly 10y-3m spread of the past 18 months        (recent deep inversion = high)
  mfg           MINUS the 3-month average of the Philly / Empire survey average     (weak factories = high)
  nfci          NFCI (above 0 = tighter than average)                               higher = worse
  jolts_layoffs JOLTS layoffs rate minus 6 months earlier (points)                  higher = worse   (with-JOLTS run only)
  jolts_hires   MINUS (JOLTS hires rate minus 6 months earlier)                     (fewer hires = high)
  claims_low_v, claims_yoy_v, cont_yoy_v
                the three claims measures recomputed from FRED's claims VINTAGES (2010 on only), for the
                claims-revision sensitivity run

The first four columns and nfci / temp_help / mfg come from the same code as the Layer 1 triggers
(src/model/triggers.py), so the score and the triggers always agree on the data.

Run it (after triggers.py):
    python src/model/features.py
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "model"))
from realtime import as_known_on                                              # noqa: E402
from triggers import claims_vs_low_of, claims_yoy_of, cont_yoy_of, yield_spread  # noqa: E402

MODEL = ROOT / "data" / "model"
OUT = MODEL / "features_monthly.csv"
YIELD_LOOKBACK = 18          # months: "recently inverted" = lowest spread of the past 18 months
VINTAGE_CLAIMS_FROM = "2010-01-01"   # claims vintages start mid-2009; 52 weeks of history needed after that


def six_month_change(series: pd.Series):
    """Latest value minus the value 6 months earlier (monthly series); None if not available."""
    s = series.dropna()
    if len(s) < 7:
        return None
    then = s.get(s.index[-1] - pd.DateOffset(months=6))
    return None if then is None or pd.isna(then) else s.iloc[-1] - then


def main() -> None:
    trig = pd.read_csv(MODEL / "triggers_monthly.csv", parse_dates=["month"]).set_index("month")
    spread = yield_spread()

    rows = []
    for m in trig.index:
        d = m + pd.offsets.MonthEnd(0)                 # as-of date = last day of the month
        t = trig.loc[m]
        row = {
            "month": m,
            # Straight from the Layer 1 trigger table (same as-of date, same code):
            "sahm": t.sahm_value,
            "claims_low": t.claims_vs_low_value,
            "claims_yoy": t.claims_yoy_value,
            "cont_yoy": t.cont_claims_yoy_value,
            "temp_help": -t.temp_help_value if pd.notna(t.temp_help_value) else None,
            "nfci": t.nfci_value,
        }
        # Yield curve: market rates are never revised, so the spread series is the same at every date.
        past = spread[(spread.index <= m) & (spread.index > m - pd.DateOffset(months=YIELD_LOOKBACK))]
        row["yield_curve"] = -past.min() if len(past) == YIELD_LOOKBACK else None
        # Manufacturing: 3-month average of the Philly / Empire average, as known at d.
        both = pd.concat([as_known_on("GACDFSA066MSFRBPHI", d), as_known_on("GACDISA066MSFRBNY", d)],
                         axis=1).mean(axis=1).dropna()
        row["mfg"] = -both.iloc[-3:].mean() if len(both) >= 3 else None
        # JOLTS (data from Dec 2000): 6-month changes, as known at d.
        lay = six_month_change(as_known_on("JTSLDR", d))
        hire = six_month_change(as_known_on("JTSHIR", d))
        row["jolts_layoffs"] = lay
        row["jolts_hires"] = -hire if hire is not None else None
        # Claims measures from the claims vintages (sensitivity run only).
        if m >= pd.Timestamp(VINTAGE_CLAIMS_FROM):
            ic4 = as_known_on("IC4WSA_vintage", d).dropna()
            cc = as_known_on("CCSA_vintage", d).dropna()
            row["claims_low_v"] = claims_vs_low_of(ic4)
            row["claims_yoy_v"] = claims_yoy_of(ic4)
            row["cont_yoy_v"] = cont_yoy_of(cc)
        rows.append(row)

    df = pd.DataFrame(rows).set_index("month").astype(float).round(4)
    df.to_csv(OUT, date_format="%Y-%m-%d")
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(df)} months")
    for c in df.columns:
        first = df[c].first_valid_index()
        print(f"  {c:14} from {first:%Y-%m}" if first is not None else f"  {c:14} (empty)")


if __name__ == "__main__":
    main()
