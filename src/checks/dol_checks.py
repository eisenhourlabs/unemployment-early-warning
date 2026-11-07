"""
Checks on the DOL data. Run after the DOL fetchers and src/transforms/dol_rates.py.

1. FRED cross-check (fails the run): national initial and continued claims NSA from the ETA 539 report
   must match FRED's ICNSA and CCNSA within 1% every week since 1995. Only official ETA 539 weeks are
   compared; preliminary news-release weeks are ignored.
2. Rate validation (report only): our SA continuing claims rate (CCSA / covered employment) vs DOL's
   published SA insured unemployment rate. DOL rounds its rate to 1 decimal, so differences up to
   0.05 percentage points are rounding; only differences clearly above 0.05 are listed.

Exit code 1 (red GitHub run) only if check 1 fails.
Run:  python src/checks/dol_checks.py
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DOL_DIR = ROOT / "data" / "processed" / "dol"
FRED_DIR = ROOT / "data" / "processed"

MAX_PCT_DIFF = 1.0           # check 1 limit, percent
IUR_TOLERANCE = 0.05 + 1e-6  # check 2 limit, percentage points (0.05 rounding + float noise)


def fred_cross_check() -> bool:
    dol = pd.read_csv(DOL_DIR / "national_weekly_eta539.csv").set_index("week_ended")
    ok = True
    for col, fred_id in [("ic_nsa", "ICNSA"), ("cc_nsa", "CCNSA")]:
        fred = pd.read_csv(FRED_DIR / f"{fred_id}.csv").set_index("date")["value"]
        both = pd.concat([dol[col], fred], axis=1, keys=["dol", "fred"]).dropna()
        pct = (both.dol / both.fred - 1).abs() * 100
        bad = pct[pct > MAX_PCT_DIFF]
        print(f"  {col} vs FRED {fred_id}: {len(both)} weeks compared "
              f"({both.index.min()} to {both.index.max()}), max difference {pct.max():.3f}%, "
              f"{len(bad)} weeks above {MAX_PCT_DIFF}%")
        for week, p in bad.head(10).items():
            print(f"     {week}: DOL {both.dol[week]:,.0f} vs FRED {both.fred[week]:,.0f} ({p:.2f}%)")
        ok &= bad.empty
    return ok


def iur_validation() -> None:
    r = pd.read_csv(DOL_DIR / "claims_rates_weekly.csv").dropna(subset=["cc_rate_sa", "iur_sa_published"])
    diff = (r.cc_rate_sa - r.iur_sa_published).abs()
    flagged = r[diff > IUR_TOLERANCE]
    print(f"  cc_rate_sa vs published IUR SA: {len(r)} weeks, max difference {diff.max():.3f} pp, "
          f"{len(flagged)} weeks above 0.05 pp")
    for _, row in flagged.head(20).iterrows():
        print(f"     {row.week_ended}: ours {row.cc_rate_sa:.3f} vs DOL {row.iur_sa_published:.1f}")


def main() -> int:
    print("Check 1: DOL vs FRED (fails the run above 1%)")
    ok = fred_cross_check()
    print("Check 2: SA continuing claims rate vs DOL's IUR (report only)")
    iur_validation()
    if not ok:
        print("\nDOL CHECKS FAILED: DOL and FRED claims differ by more than 1% (see above).")
        return 1
    print("\nDOL checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
