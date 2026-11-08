"""
Stage 3d, B6: compare our unemployment-rate fan centers with published forecasts (comparison only; nothing on the
site). Both benchmarks forecast QUARTERLY averages, so our centers (horizons 3 / 6 / 12 months after the latest
published month, plus today's level at horizon 0) are interpolated to each month of the target quarter and averaged.
Only quarters within our 12-month reach are compared. Two timings: "strict" (our origin is the last month end
BEFORE publication: we never know more, but we know one month LESS of the unemployment rate, since both
benchmarks are made after that month's release) and "matched" (our origin is the end of the publication month: the
same unemployment-rate release, plus about two more weeks of claims).

  FOMC SEP   FRED UNRATEMD (median projection of the Q4 average unemployment rate; one ALFRED vintage per SEP
             release, from December 2015). Compared: Q4 of the release year (every SEP) and Q4 of the next year
             (December SEPs only).
  SPF        Philadelphia Fed Survey of Professional Forecasters, median level file, sheet UNEMP (quarterly; columns
             UNEMP3..UNEMP6 = 1..4 quarters after the survey quarter). Surveys are taken in the middle of the
             quarter's second month. The SPF file is "all rights reserved" (Philadelphia Fed), so it is read from
             outside the repository (path given on the command line) and only summary statistics are saved.

Writes data/model/benchmark_summary.csv.
Run it:  python src/model/benchmarks.py <path to medianLevel.xlsx>
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "fetchers"))
from fred_fetcher import fred_get, load_api_key    # noqa: E402

MODEL = ROOT / "data" / "model"
COVID_Q = (pd.Timestamp("2020-04-01"), pd.Timestamp("2021-03-01"))   # target quarters reported separately


def months_between(a, b):
    return (b.year - a.year) * 12 + b.month - a.month


def our_centers():
    bt = pd.read_csv(MODEL / "forecast_backtest.csv", parse_dates=["origin", "latest_period"])
    ur = bt[bt.target == "ur"]
    out = {}
    for m, g in ur.groupby("origin"):
        pts = {0: g.level_at_origin.iloc[0], **dict(zip(g.horizon, g.center))}
        out[m] = (g.latest_period.iloc[0], g.level_at_origin.iloc[0], pts)
    return out


def interp(pts: dict, k: int) -> float:
    ks = sorted(pts)
    return float(np.interp(k, ks, [pts[x] for x in ks]))


def compare(cases, label, centers, final, matched=False):
    """cases: list of (published date, target quarter's first month, benchmark value, bucket)."""
    rows = []
    for published, q_start, bench, bucket in cases:
        # strict: last month end before publication (we know one month LESS of the unemployment rate);
        # matched: end of the publication month (same unemployment-rate release, ~2 more weeks of claims).
        origin = published.replace(day=1) - pd.DateOffset(months=0 if matched else 1)
        if origin not in centers:
            continue
        L, y0, pts = centers[origin]
        months = [q_start + pd.DateOffset(months=i) for i in range(3)]
        ks = [months_between(L, m) for m in months]
        if max(ks) > 12 or min(ks) < 1:
            continue
        actual = final.reindex(months).mean()                 # a missing month (Oct 2025) is skipped
        if pd.isna(actual):
            continue
        rows.append({"benchmark": label, "bucket": bucket, "timing": "matched" if matched else "strict", "published": published, "target_quarter": q_start,
                     "covid": COVID_Q[0] <= q_start <= COVID_Q[1], "ours": np.mean([interp(pts, k) for k in ks]),
                     "benchmark_value": bench, "no_change": y0, "actual": actual})
    return rows


def main(spf_path: str) -> None:
    final = pd.read_csv(ROOT / "data" / "processed" / "UNRATE.csv", parse_dates=["date"]).set_index("date")["value"]
    centers = our_centers()
    key = load_api_key()

    # FOMC SEP (every vintage of UNRATEMD).
    obs = fred_get("series/observations", {"series_id": "UNRATEMD", "realtime_start": "1776-07-04",
                                           "realtime_end": "9999-12-31"}, key)["observations"]
    sep = pd.DataFrame(obs)
    sep["value"] = pd.to_numeric(sep.value, errors="coerce")
    sep["year"] = sep.date.str[:4].astype(int)
    sep["published"] = pd.to_datetime(sep.realtime_start)
    cases = []
    for r in sep.dropna(subset=["value"]).itertuples():
        if r.year == r.published.year:
            cases.append((r.published, pd.Timestamp(f"{r.year}-10-01"), r.value, f"SEP {r.published:%b} -> Q4 same year"))
        elif r.year == r.published.year + 1 and r.published.month == 12:
            cases.append((r.published, pd.Timestamp(f"{r.year}-10-01"), r.value, "SEP Dec -> Q4 next year"))
    rows = compare(cases, "FOMC SEP median", centers, final) + compare(cases, "FOMC SEP median", centers, final, True)

    # SPF median (surveys from 2000).
    spf = pd.read_excel(spf_path, sheet_name="UNEMP")
    cases = []
    for r in spf.itertuples():
        if r.YEAR < 2000:
            continue
        survey_q = pd.Timestamp(year=int(r.YEAR), month=3 * (int(r.QUARTER) - 1) + 1, day=1)
        published = survey_q + pd.DateOffset(months=1, days=14)   # mid second month of the quarter
        for j, col in enumerate(["UNEMP3", "UNEMP4", "UNEMP5", "UNEMP6"], start=1):
            v = getattr(r, col)
            if pd.notna(v):
                cases.append((published, survey_q + pd.DateOffset(months=3 * j), float(v), f"SPF {j} quarter(s) ahead"))
    rows += compare(cases, "SPF median", centers, final) + compare(cases, "SPF median", centers, final, True)

    df = pd.DataFrame(rows)
    summ = []
    for (b, bucket, timing, covid), g in df.groupby(["benchmark", "bucket", "timing", "covid"]):
        e = lambda col: g[col] - g.actual
        summ.append({"benchmark": b, "bucket": bucket, "timing": timing, "covid_quarters": covid, "cases": len(g),
                     "first": f"{g.published.min():%Y-%m}", "last": f"{g.published.max():%Y-%m}",
                     "mae_ours": e("ours").abs().mean(), "mae_benchmark": e("benchmark_value").abs().mean(),
                     "mae_no_change": e("no_change").abs().mean(),
                     "rmse_ours": np.sqrt((e("ours") ** 2).mean()), "rmse_benchmark": np.sqrt((e("benchmark_value") ** 2).mean()),
                     "rmse_no_change": np.sqrt((e("no_change") ** 2).mean())})
    s = pd.DataFrame(summ)
    s.to_csv(MODEL / "benchmark_summary.csv", index=False)
    pd.set_option("display.width", 250)
    print(s.round(3).to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1])
