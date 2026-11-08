"""
Inputs for the early-warning score: candidate indicators as continuous values, SIGNED SO THAT HIGHER MEANS
WORSE, using only what was published by the as-of date.

features_at(d) computes every input as known on date d (any date: month ends for the score, Thursdays for the
weekly colour-stability test). main() writes one row per month (as of each month's last day) to
data/model/features_monthly.csv.

Columns:
  sahm          Sahm indicator (points)                                            higher = worse
  claims_low    SA initial claims 4-wk avg vs. its 52-week low (ratio - 1)          higher = worse
  claims_yoy    SA initial claims 4-wk avg vs. a year ago                           higher = worse
  cont_yoy      SA continued claims (4-wk avg) vs. a year ago                       higher = worse
  temp_help     MINUS the 6-month % change in temp help jobs                        (a fall = positive)
  yield_curve   MINUS the lowest monthly 10y-3m spread of the past 18 months        (recent deep inversion = high)
  mfg           MINUS the 3-month average of the Philly / Empire survey average     (weak factories = high)
  nfci          NFCI (above 0 = tighter than average)                               higher = worse
  jolts_layoffs JOLTS layoffs rate minus 6 months earlier (points)                  higher = worse   (tested, not used)
  jolts_hires   MINUS (JOLTS hires rate minus 6 months earlier)                     (fewer hires = high)
  nsa_yoy       NSA initial claims 4-wk avg vs. the same weeks a year earlier       higher = worse   (stage 3d test)
  nsa_low       nsa_yoy's ratio (1 + nsa_yoy) minus its lowest value of the prior 52 weeks       (stage 3d test)
  claims_low_v, claims_yoy_v, cont_yoy_v, nsa_yoy_v, nsa_low_v
                the claims measures recomputed from FRED's claims VINTAGES (2010 on only), for the
                real-time sensitivity runs

The Sahm / claims / temp help / NFCI values use the same code as the Layer 1 triggers (src/model/triggers.py).

Run it (after triggers.py):
    python src/model/features.py
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "model"))
from realtime import as_known_on, sahm                                                      # noqa: E402
from triggers import YEAR, claims_vs_low_of, claims_yoy_of, cont_yoy_of, yield_spread      # noqa: E402

MODEL = ROOT / "data" / "model"
OUT = MODEL / "features_monthly.csv"
YIELD_LOOKBACK = 18                   # months: "recently inverted" = lowest spread of the past 18 months
YIELD_LAG = pd.Timedelta(days=27)     # a month's average spread is complete by its last day (see model_series.csv)
VINTAGE_CLAIMS_FROM = "2010-01-01"    # claims vintages start mid-2009; 52 weeks of history needed after that
SPREAD = None                         # the yield spread series, loaded once


def six_month_change(series: pd.Series):
    """Latest value minus the value 6 months earlier (monthly series); None if not available."""
    s = series.dropna()
    if len(s) < 7:
        return None
    then = s.get(s.index[-1] - pd.DateOffset(months=6))
    return None if then is None or pd.isna(then) else s.iloc[-1] - then


def nsa_measures(icnsa: pd.Series):
    """(nsa_yoy, nsa_low) from weekly NSA initial claims. Comparing with the same weeks a year earlier removes
    most of the seasonal pattern without using seasonal factors."""
    s = icnsa.dropna()
    ma4 = s.rolling(4).mean()
    ratio = (ma4 / ma4.shift(freq=YEAR).reindex(ma4.index)).dropna()   # 4-wk avg vs. the same weeks a year ago
    if len(ratio) == 0:
        return None, None
    yoy = ratio.iloc[-1] - 1
    low = ratio.iloc[-1] - ratio.iloc[-53:-1].min() if len(ratio) >= 53 else None
    return yoy, low


def features_at(d: pd.Timestamp) -> dict:
    """Every input as it was known on date d."""
    global SPREAD
    if SPREAD is None:
        SPREAD = yield_spread()
    row = {}
    ur = as_known_on("UNRATE", d).asfreq("MS")
    row["sahm"] = round(sahm(ur), 2) if len(ur) >= 15 else None
    ic4 = as_known_on("IC4WSA", d).dropna()
    cc = as_known_on("CCSA", d).dropna()
    row["claims_low"] = claims_vs_low_of(ic4)
    row["claims_yoy"] = claims_yoy_of(ic4)
    row["cont_yoy"] = cont_yoy_of(cc)
    th = as_known_on("TEMPHELPS", d).dropna()
    then = th.get(th.index[-1] - pd.DateOffset(months=6)) if len(th) >= 7 else None
    row["temp_help"] = -(th.iloc[-1] / then - 1) if then is not None and pd.notna(then) else None
    nf = as_known_on("NFCI", d).dropna()
    row["nfci"] = round(float(nf.iloc[-1]), 2) if len(nf) else None
    # Yield curve: market rates are never revised; a month counts once its average is complete.
    past = SPREAD[SPREAD.index + YIELD_LAG <= d].iloc[-YIELD_LOOKBACK:]
    row["yield_curve"] = -past.min() if len(past) == YIELD_LOOKBACK else None
    both = pd.concat([as_known_on("GACDFSA066MSFRBPHI", d), as_known_on("GACDISA066MSFRBNY", d)],
                     axis=1).mean(axis=1).dropna()
    row["mfg"] = -both.iloc[-3:].mean() if len(both) >= 3 else None
    lay = six_month_change(as_known_on("JTSLDR", d))
    hire = six_month_change(as_known_on("JTSHIR", d))
    row["jolts_layoffs"] = lay
    row["jolts_hires"] = -hire if hire is not None else None
    row["nsa_yoy"], row["nsa_low"] = nsa_measures(as_known_on("ICNSA", d))
    if d >= pd.Timestamp(VINTAGE_CLAIMS_FROM):
        ic4v = as_known_on("IC4WSA_vintage", d).dropna()
        ccv = as_known_on("CCSA_vintage", d).dropna()
        row["claims_low_v"] = claims_vs_low_of(ic4v)
        row["claims_yoy_v"] = claims_yoy_of(ic4v)
        row["cont_yoy_v"] = cont_yoy_of(ccv)
        row["nsa_yoy_v"], row["nsa_low_v"] = nsa_measures(as_known_on("ICNSA_vintage", d))
    return row


def main() -> None:
    trig = pd.read_csv(MODEL / "triggers_monthly.csv", parse_dates=["month"]).set_index("month")
    rows = [{"month": m, **features_at(m + pd.offsets.MonthEnd(0))} for m in trig.index]
    df = pd.DataFrame(rows).set_index("month").astype(float).round(4)
    df.to_csv(OUT, date_format="%Y-%m-%d")
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(df)} months")
    for c in df.columns:
        first = df[c].first_valid_index()
        print(f"  {c:14} from {first:%Y-%m}" if first is not None else f"  {c:14} (empty)")


if __name__ == "__main__":
    main()
