"""
Review WP8 test T2 (finding I1 part 2): the Duration watch on data as known at the time.

Pre-registration: docs/model_tests_severity_watch.md (committed before this script).

The WP5 backtest (severity_watch.py) put each month in a band using today's revised continuing claims and the last
week ending in the month. Here the band of month t comes from continuing claims vs. a year ago AS KNOWN at the month
end: cont_yoy_of(as_known_on("CCSA", month end)), i.e. current-vintage claims cut back by the 12-day release lag (the
value of the continuing-claims confirmation trigger), and from 2010 also on claims as first published
(as_known_on("CCSA_vintage", month end)). Outcomes (on final data) and the bands are those of severity_watch.py.

Rule (fixed): show the percentages only if, in BOTH 1968-1999 and 2000-2026 and for BOTH outcomes (lt_share_up,
median_up), on the real-time basis: red share >= 0.50, falling share <= 0.10, and the shares rise strictly from
falling to green to amber to red (a band with no months fails).

Writes data/model/severity_watch_realtime.csv (basis, window, outcome, band, months, share_followed) and
data/model/severity_watch_realtime_monthly.csv (month, cc_yoy_realtime, cc_yoy_first_published, band of each).
Run:  python src/model/severity_watch_realtime.py   (after severity_watch.py; ~1 min)
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "model"))
import severity_watch as sw                # noqa: E402  (bands, outcomes, 2019-21 exclusion)
from realtime import as_known_on           # noqa: E402
from triggers import cont_yoy_of           # noqa: E402  (the continuing-claims trigger value)

MODEL = ROOT / "data" / "model"
OUTCOMES = ["lt_share_up", "median_up"]
FIRST_PUBLISHED_FROM = "2010-01-01"        # FRED claims vintages start 2009-09; a year of history is needed
RULE_WINDOWS = {"1968-1999": ("1968-01-01", "1999-12-01"), "2000-2026": ("2000-01-01", "2026-12-01")}
REPORT_WINDOWS = {**RULE_WINDOWS, "2010-2026": ("2010-01-01", "2026-12-01"), "1968-2026": ("1968-01-01", "2026-12-01")}


def realtime_cc_yoy(months: pd.DatetimeIndex, series_id: str) -> pd.Series:
    """Continuing claims vs. a year ago as known at each month end (None where there is not a year of history)."""
    out = {}
    for m in months:
        cc = as_known_on(series_id, m + pd.offsets.MonthEnd(0)).dropna()
        out[m] = cont_yoy_of(cc) if len(cc) else None
    return pd.Series(out, dtype=float)


def shares(f: pd.DataFrame, band_col: str, start: str, end: str) -> list[dict]:
    """Months and share followed by each outcome, by band, for band months in [start, end]."""
    use = f[~f.excluded & f[band_col].notna() & (f.index >= start) & (f.index <= end)]
    rows = []
    for outcome in OUTCOMES:
        o = use.dropna(subset=[outcome])
        for band in sw.BANDS:
            b = o[o[band_col] == band]
            rows.append({"outcome": outcome, "band": band, "months": len(b),
                         "share_followed": float(b[outcome].astype(float).mean()) if len(b) else None})
        rows.append({"outcome": outcome, "band": "base_rate", "months": len(o),
                     "share_followed": float(o[outcome].astype(float).mean()) if len(o) else None})
    return rows


def rule_ok(rows: list[dict]) -> dict:
    """The fixed rule for one window (rows of shares()): per outcome, red >= 0.50, falling <= 0.10, strict rise."""
    out = {}
    for outcome in OUTCOMES:
        s = [next(r["share_followed"] for r in rows if r["outcome"] == outcome and r["band"] == b) for b in sw.BANDS]
        if any(v is None for v in s):
            out[outcome] = False                     # a band with no months: cannot show a rise
            continue
        out[outcome] = bool(s[3] >= 0.50 and s[0] <= 0.10 and all(b > a for a, b in zip(s, s[1:])))
    return out


def main() -> None:
    f = sw.build_frame()                                    # outcomes on final data, the WP5 revised-data band
    f["cc_yoy_realtime"] = realtime_cc_yoy(f.index, "CCSA")
    fp = f.index[f.index >= FIRST_PUBLISHED_FROM]
    f["cc_yoy_first_published"] = realtime_cc_yoy(fp, "CCSA_vintage").reindex(f.index)
    f["band_realtime"] = f.cc_yoy_realtime.map(sw.band_of)
    f["band_first_published"] = f.cc_yoy_first_published.map(sw.band_of)

    rows = []
    bases = {"real time (current vintage, 12-day lag)": "band_realtime",
             "first published (2010 on)": "band_first_published", "revised, WP5 (no lag)": "band"}
    for basis, col in bases.items():
        for window, (a, b) in REPORT_WINDOWS.items():
            if col == "band_first_published" and window != "2010-2026":
                continue
            for r in shares(f, col, a, b):
                rows.append({"basis": basis, "window": window, **r})
    out = pd.DataFrame(rows)
    out.to_csv(MODEL / "severity_watch_realtime.csv", index=False, float_format="%.4f")
    m = f[["cc_yoy", "cc_yoy_realtime", "cc_yoy_first_published", "band", "band_realtime", "band_first_published"]]
    m = m.dropna(subset=["cc_yoy_realtime"]).rename(columns={"cc_yoy": "cc_yoy_revised_wp5", "band": "band_revised_wp5"})
    m.to_csv(MODEL / "severity_watch_realtime_monthly.csv", date_format="%Y-%m", index_label="month", float_format="%.4f")

    with pd.option_context("display.width", 200):
        for (basis, window), g in out.groupby(["basis", "window"], sort=False):
            t = g.pivot(index="band", columns="outcome", values="share_followed").reindex(sw.BANDS + ["base_rate"])
            n = g[g.outcome == "lt_share_up"].set_index("band").months.reindex(sw.BANDS + ["base_rate"])
            print(f"\n{basis}, {window}:")
            print(t.assign(months=n).round(3).to_string())
    same = (f.band_realtime == f.band)[f.band_realtime.notna() & f.band.notna() & ~f.excluded]
    print(f"\nMonths in the same band on real-time and WP5 revised data: {same.mean():.1%} of {len(same)}")
    samev = (f.band_first_published == f.band_realtime)[f.band_first_published.notna() & ~f.excluded]
    print(f"Months in the same band, first published vs. real-time current vintage (2010 on): {samev.mean():.1%} "
          f"of {len(samev)}")

    print("\nRule (pre-registered), real-time basis:")
    verdict = True
    for window, (a, b) in RULE_WINDOWS.items():
        ok = rule_ok(shares(f, "band_realtime", a, b))
        verdict &= all(ok.values())
        print(f"  {window}: " + "; ".join(f"{k} {'passes' if v else 'FAILS'}" for k, v in ok.items()))
    print("Result: " + ("PASSED: the percentages may be shown (with Troy's approval)" if verdict
                        else "FAILED: the bracketed words-only wording stays"))


if __name__ == "__main__":
    main()
