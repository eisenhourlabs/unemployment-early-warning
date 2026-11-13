"""
Review WP8 test T1 (finding F5): the chance of a large rise, read off a fan's simulated draws.

Pre-registration: docs/model_tests_tail_probability.md. Used by forecast.py (backtest), live.py (live fans) and
forecast_regimes.py (reliability table), so all three use exactly the same definition.

  p_rise_050    unemployment rate: share of draws at least 0.5 point above the level at the origin
  p_rise_20pct  continuing claims rate: share of draws at least 20% above the level at the origin

A tolerance of 1e-9 makes a rise of exactly 0.5 point count (4.1 -> 4.6 is not exactly +0.5 in binary floating point).
"""
import numpy as np

TOL = 1e-9
# Reliability bins of the stated probability: [0, 0.10), [0.10, 0.25), [0.25, 0.50), [0.50, 1]
BINS = [0.0, 0.10, 0.25, 0.50]
BIN_LABELS = ["0-10%", "10-25%", "25-50%", "50-100%"]


def threshold(target: str, y0: float) -> float:
    """The level that counts as a large rise from y0: +0.5 point (unemployment rate) or +20% (continuing claims)."""
    return y0 + 0.5 if target == "ur" else 1.2 * y0


def met(target: str, y0, values) -> np.ndarray:
    """True where a value (draw or realized outcome) is at or above the large-rise level."""
    return np.asarray(values, float) >= threshold(target, np.asarray(y0, float)) - TOL


def p_rise_050(levels, y0: float) -> float:
    return float(np.mean(met("ur", y0, levels)))


def p_rise_20pct(levels, y0: float) -> float:
    return float(np.mean(met("cc", y0, levels)))


def p_rise(target: str, levels, y0: float):
    """The T1 probability for a fan target, or None for targets it does not apply to (initial claims)."""
    if target == "ur":
        return p_rise_050(levels, y0)
    if target == "cc":
        return p_rise_20pct(levels, y0)
    return None


def column(target: str) -> str | None:
    return {"ur": "p_rise_050", "cc": "p_rise_20pct"}.get(target)


def bin_label(p: float) -> str:
    """The reliability bin of a stated probability."""
    return BIN_LABELS[int(np.searchsorted(BINS, p, side="right")) - 1]


def rule(table) -> dict:
    """The fixed rule of T1 for one target-horizon's bins (rows in bin order, base_rate row excluded): returns
    {"monotone": (a), "calibrated": (b), "show": (a) and (b)}.
    (a) observed rises (strictly) from each non-empty bin to the next; fewer than two non-empty bins fails.
    (b) every bin with 20+ origins has |observed - mean_stated| <= 0.15."""
    rows = [r for r in table if r["origins"] > 0]
    obs = [r["observed"] for r in rows]
    monotone = len(obs) >= 2 and all(b > a for a, b in zip(obs, obs[1:]))
    calibrated = all(abs(r["observed"] - r["mean_stated"]) <= 0.15 for r in rows if r["origins"] >= 20)
    return {"monotone": bool(monotone), "calibrated": bool(calibrated), "show": bool(monotone and calibrated)}
