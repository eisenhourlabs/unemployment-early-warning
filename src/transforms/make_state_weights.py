"""
Regenerate config/state_weights.csv (committed) from internal/state_weights_private.csv (private, git-ignored).

Run this on Troy's PC after refreshing the private branch counts (the cloud has no private file):
    python src/transforms/make_state_weights.py

Output columns:
  state, state_name
  footprint_rank  1 = most branches; tied states share a rank (1, 2, 2, 4, ...)
  weight          branch share = branches / total, rounded to 6 decimals so that the column sums to exactly 1
                  (largest-remainder rounding: round everything down, then give the leftover millionths to the
                  states with the largest rounding remainders). States not listed have weight 0.

Phase 4 decision O2: the exact weights are committed, so the cloud build and live runs can read them.
The data-source note stays in internal/ only; this file names no company or source.
"""

from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / "internal" / "state_weights_private.csv"
PUBLIC = ROOT / "config" / "state_weights.csv"
DECIMALS = 6


def share_weights(counts: pd.Series, decimals: int = DECIMALS) -> pd.Series:
    """Shares of the total, rounded to `decimals` places, summing to exactly 1 (largest remainder)."""
    unit = 10 ** decimals
    exact = counts / counts.sum() * unit           # shares in millionths
    whole = exact.astype(int)                       # rounded down (shares are positive)
    leftover = unit - whole.sum()                   # millionths still to hand out
    order = (exact - whole).sort_values(ascending=False, kind="mergesort").index
    whole[order[:leftover]] += 1
    return whole / unit


def build(private: pd.DataFrame) -> pd.DataFrame:
    df = private[["state", "state_name", "branches"]].copy()
    df = df.sort_values(["branches", "state"], ascending=[False, True]).reset_index(drop=True)
    df["footprint_rank"] = df.branches.rank(method="min", ascending=False).astype(int)
    df["weight"] = share_weights(df.branches).values
    return df[["state", "state_name", "footprint_rank", "weight"]]


def main():
    private = pd.read_csv(PRIVATE, comment="#")
    out = build(private)
    header = (f"# Footprint weights: 1 = largest exposure; ties share a rank. weight = share of the total "
              f"({DECIMALS} decimals, sums to 1; 0 for states not listed). {len(out)} states. "
              f"Generated {date.today().isoformat()} by src/transforms/make_state_weights.py.\n")
    with open(PUBLIC, "w", newline="", encoding="utf-8") as f:
        f.write(header)
        out.to_csv(f, index=False, float_format=f"%.{DECIMALS}f", lineterminator="\n")
    print(f"Wrote {PUBLIC.relative_to(ROOT)}: {len(out)} states, weights sum to {out.weight.sum():.6f}")


if __name__ == "__main__":
    main()
