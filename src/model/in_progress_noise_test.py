"""
Review WP8 test T3 (finding F2 part 3): wider ranges once an event is under way. Compares the forecast backtest
without the change (data/model/forecast_backtest.csv, forecast_evaluation.csv) and with it
(forecast_backtest_ipnoise.csv, forecast_evaluation_ipnoise.csv from `forecast.py --from 1985 --option ipnoise`).

Pre-registration: docs/model_tests_in_progress_noise.md (committed before this script).

Measures by regime (forecast_regimes.py: "during an event" = in progress 3+ months on the real-time event state;
"all" = every origin), windows 1985-1999 and 2000-2026: cover80, above_q90, rmse_ratio (and origins).
Rule (fixed), unemployment rate, 2000-2026, with the change:
  (1) during-an-event cover80 >= 0.70 at every horizon;
  (2) overall cover80 within 0.75-0.85 at every horizon;
  (3) |overall RMSE ratio with - without| < 0.02 at every horizon;
  (4) every target-horizon shown on the site (ur 3 / 6 / 12, cc 13) passes the existing gate.

Writes data/model/forecast_in_progress_noise_test.csv.
Run:  python src/model/in_progress_noise_test.py     (after both forecast.py runs)
"""
from pathlib import Path

import pandas as pd

import forecast_regimes as fr

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "data" / "model"
WINDOWS = {"1985-1999": ("1985-01-01", "1999-12-01"), "2000-2026": ("2000-01-01", None)}
SHOWN = [("ur", 3), ("ur", 6), ("ur", 12), ("cc", 13)]


def main() -> None:
    ev, state = fr.load_events(), fr.realtime_state()
    versions = {"without": "", "with": "_ipnoise"}
    rows = []
    for version, suffix in versions.items():
        bt = pd.read_csv(MODEL / f"forecast_backtest{suffix}.csv", parse_dates=["origin"])
        for window, (a, b) in WINDOWS.items():
            t = fr.evaluate(bt, ev, state, start=a, end=b)
            rows += [{"version": version, "window": window, **r} for r in t.to_dict("records")]
    out = pd.DataFrame(rows)
    out.round(4).to_csv(MODEL / "forecast_in_progress_noise_test.csv", index=False)

    keep = out[out.regime.isin(["during an event", "all"])]
    show = keep.pivot_table(index=["window", "target", "horizon", "regime"], columns="version",
                            values=["cover80", "above_q90", "rmse_ratio", "origins"], sort=False)
    with pd.option_context("display.width", 220, "display.max_rows", 200):
        print(show.round(3).to_string())

    # the fixed rule
    g = out[(out.window == "2000-2026") & (out.target == "ur")]
    pick = lambda version, regime, h, col: float(g[(g.version == version) & (g.regime == regime)
                                                   & (g.horizon == h)][col].iloc[0])
    checks = {}
    for h in (3, 6, 12):
        checks[f"ur {h}m: during-an-event cover80 >= 0.70"] = pick("with", "during an event", h, "cover80") >= 0.70
        checks[f"ur {h}m: overall cover80 in 0.75-0.85"] = 0.75 <= pick("with", "all", h, "cover80") <= 0.85
        d = pick("with", "all", h, "rmse_ratio") - pick("without", "all", h, "rmse_ratio")
        checks[f"ur {h}m: overall RMSE ratio change {d:+.3f} (< 0.02 in size)"] = abs(d) < 0.02
    ev_with = pd.read_csv(MODEL / "forecast_evaluation_ipnoise.csv")
    for t, h in SHOWN:
        r = ev_with[(ev_with.target == t) & (ev_with.horizon == h) & (ev_with.subset == "2000-on excl. 2020")].iloc[0]
        checks[f"gate {t} {h}: cover50 {r.cover50:.2f}, cover80 {r.cover80:.2f}, RMSE ratio {r.rmse_ratio:.2f}"] = \
            bool(r.gate_pass)
    print("\nRule (pre-registered), with the change:")
    for k, v in checks.items():
        print(f"  {'yes' if v else 'NO '}  {k}")
    adopted = all(checks.values())
    print("Result: " + ("ADOPTED (enters through the January 2027 re-fit pull request)" if adopted
                        else "not adopted: the model and the WP3 wording stay"))
    bt_with = pd.read_csv(MODEL / "forecast_backtest_ipnoise.csv", parse_dates=["origin"])
    ip = bt_with[bt_with.noise_source != "quiet"]
    print("\nNoise source at in-progress origins (all windows):")
    print(ip.groupby(["target", "horizon", "noise_source"]).agg(origins=("origin", "size"),
                                                                pool_min=("noise_pool_size", "min"),
                                                                pool_max=("noise_pool_size", "max")).to_string())


if __name__ == "__main__":
    main()
