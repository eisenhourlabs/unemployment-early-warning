"""
Step 1 of the modeling data: one weekly claims table from 1967.

What it does:
  1. Reads FRED's SA initial claims (ICSA), its 4-week average (IC4WSA) and SA continuing claims (CCSA)
     from data/processed/ (the FRED fetcher keeps these from January 1967).
  2. Adds covered employment and the SA initial / continuing claims rates from the DOL national report
     (data/processed/dol/claims_rates_weekly.csv). Covered employment, the rates' denominator, starts in
     the week ending 1971-01-02; DOL leaves it blank for 1967-1970, so the rates start in 1971.
  3. Flags weeks before 1978, when UI coverage expanded (state and local government workers), because
     rates before and after are not strictly comparable.
  4. Writes data/model/claims_weekly.csv.

All values are today's (current-vintage) figures: DOL claims are not kept as vintages (decision 2026-11-08).

Run it (after the FRED fetch and the DOL pipeline):
    python src/model/build_claims_history.py
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
OUT = ROOT / "data" / "model" / "claims_weekly.csv"


def read_fred(series_id: str) -> pd.Series:
    """Read one FRED file (columns date, value) as a Series indexed by date."""
    df = pd.read_csv(PROCESSED / f"{series_id}.csv", parse_dates=["date"])
    return df.set_index("date")["value"].rename(series_id)


def main() -> None:
    # FRED's weekly claims: each date is the Saturday that ends the week.
    fred = pd.concat([read_fred("ICSA"), read_fred("IC4WSA"), read_fred("CCSA")], axis=1)

    # DOL rates file: one row per week, same Saturday dates.
    dol = pd.read_csv(PROCESSED / "dol" / "claims_rates_weekly.csv", parse_dates=["week_ended"])
    dol = dol.set_index("week_ended")[["covered_employment", "ic_rate_sa", "cc_rate_sa"]]

    # Join on the week. "left" keeps every FRED week, with blank rates where DOL has none (before 1971).
    table = fred.join(dol, how="left")
    table.index.name = "week_ended"
    for col in ["ICSA", "IC4WSA", "CCSA", "covered_employment"]:
        table[col] = table[col].round().astype("Int64")   # whole numbers; "Int64" allows blanks
    table["pre_1978_coverage"] = table.index < "1978-01-01"   # True = before the 1978 coverage expansion

    OUT.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT, date_format="%Y-%m-%d")

    # A short report so you can see what was built.
    first_rate = table["ic_rate_sa"].first_valid_index()
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(table)} weeks, "
          f"{table.index[0]:%Y-%m-%d} to {table.index[-1]:%Y-%m-%d}")
    print(f"  ICSA / CCSA from {table['ICSA'].first_valid_index():%Y-%m-%d}; "
          f"IC4WSA from {table['IC4WSA'].first_valid_index():%Y-%m-%d}; claims rates from {first_rate:%Y-%m-%d}")


if __name__ == "__main__":
    main()
