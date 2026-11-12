"""
The FOMC median for NEXT year's Q4, set beside our 12-month middle value (review WP3, 2026-11).

Used by src/model/live.py (written into live_latest.json as fomc.next) and by the site (src/site/common.py), which
fills it in for a live_latest.json written before this change, because the "Publish site" run does not re-run live.py.
Only pandas: the site can import it without the model's other modules.
"""
import pandas as pd


def fomc_next(unratemd: pd.Series, year: int, ur_fan: dict) -> dict | None:
    """unratemd: the FOMC median projections (FRED UNRATEMD, latest vintage), indexed by date, one value per year
    dated 1 January. year: the current year (the main marker's year). ur_fan: live_latest.json fans.ur.

    Returns {"year", "value", "marker_date", "our_12m_median", "our_12m_period", "gap"} for year + 1, or None when
    that year has no value (or the fan has no 12-month horizon). gap = FOMC value - our 12-month middle value."""
    s = unratemd.dropna()
    key = pd.Timestamp(f"{year + 1}-01-01")
    h12 = next((h for h in ur_fan.get("horizons", []) if h.get("horizon") == 12), None)
    if key not in s.index or h12 is None:
        return None
    value = float(s[key])
    return {"year": year + 1, "value": value, "marker_date": f"{year + 1}-11-15",
            "our_12m_median": float(h12["median"]), "our_12m_period": h12["target_period"],
            "gap": value - float(h12["median"])}
