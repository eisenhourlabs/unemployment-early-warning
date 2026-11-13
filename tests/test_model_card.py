"""
The model card (docs/model_card.md) quotes the key numbers by hand. This test recomputes them from the model files
and fails if the card no longer matches, for example after the January re-fit writes new results. When it fails,
update the card (and its "What changed" table), not the test.
"""
import json
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "data" / "model"
CARD = (ROOT / "docs" / "model_card.md").read_text(encoding="utf-8")


def signed(v: float) -> str:
    """+0.18 / −0.01, with the typographic minus used in the card."""
    return f"{v:+.2f}".replace("-", "−")


def pct(v: float) -> str:
    return f"{v * 100:.0f}%"


class TestModelCard(unittest.TestCase):
    def assertInCard(self, text: str):
        if text not in CARD:
            self.fail(f"docs/model_card.md should contain {text!r} (update the card)")

    def test_frozen_model(self):
        frozen = sorted((MODEL / "frozen").glob("model_*.json"))[-1]
        m = json.loads(frozen.read_text())
        self.assertInCard(f"the {m['model_year']} model (`data/model/frozen/{frozen.name}`)")
        self.assertInCard(f"frozen on {m['frozen_at'][:10]} on data known by {m['data_known_by']}")
        c = m["colour"]
        self.assertEqual((c["amber_in"], c["amber_out"], c["red_in"], c["red_out"]), (0.2, 0.15, 0.5, 0.4))
        self.assertEqual(len(m["score"]["features"]), 8)

    def test_score_record(self):
        s = pd.read_csv(MODEL / "score_skill_summary.csv").set_index("basis")
        fp, rv = s.loc["first_published"], s.loc["revised"]
        self.assertInCard(f"{int(rv.months)} scored months, {int(rv.event_months)} of them followed by an event, "
                          f"which covers only {int(rv.events_in_test)} distinct")
        for colour, label in (("red", "Red (50%+)"), ("amber", "Amber (20–50%)"), ("green", "Green (under 20%)")):
            row = (f"| {label}: months / followed by an event")
            line = next(l for l in CARD.splitlines() if l.startswith(row))
            self.assertIn(f"{int(fp['n_' + colour])} / {pct(fp['hit_' + colour])} | "
                          f"{int(rv['n_' + colour])} / {pct(rv['hit_' + colour])} |", line)
        for r in (fp, rv):
            self.assertInCard(f"{signed(r.skill)} (90% range {signed(r.skill_p05)} to {signed(r.skill_p95)})")
        self.assertInCard(f"| {fp.auc:.2f} | {rv.auc:.2f} |")
        self.assertInCard(f"{int(rv.longest_elevated_run_months)} months, "
                          f"{pd.Timestamp(rv.longest_elevated_run_start + '-01'):%B %Y} to "
                          f"{pd.Timestamp(rv.longest_elevated_run_end + '-01'):%B %Y}")

    def test_forecast_ranges(self):
        fe = pd.read_csv(MODEL / "forecast_evaluation.csv")
        fe = fe[fe.subset == "2000-on excl. 2020"].set_index(["target", "horizon"])
        reg = pd.read_csv(MODEL / "forecast_evaluation_regimes.csv").set_index(["target", "horizon", "regime"])
        ur = [("ur", h) for h in (3, 6, 12)]
        self.assertInCard("error ratio " + " / ".join(f"{fe.loc[k].rmse_ratio:.2f}" for k in ur))
        self.assertInCard("80% range held " + " / ".join(pct(fe.loc[k].cover80) for k in ur) + " of outcomes overall")
        self.assertInCard("only " + " / ".join(pct(reg.loc[(*k, "during an event")].cover80) for k in ur))
        cc = fe.loc[("cc", 13)]
        self.assertInCard(f"error ratio {cc.rmse_ratio:.2f}; the 80% range held {pct(cc.cover80)} overall and "
                          f"{pct(reg.loc[('cc', 13, 'during an event')].cover80)} during events")
        # The card names the forecasts shown: those that pass the gate (common.apply_fan_gate)
        passing = {k for k, r in fe.iterrows() if bool(r.gate_pass) and k[0] in ("ur", "cc")}
        self.assertEqual(passing & {("cc", 26), ("cc", 52)}, set(), "the card says only cc 13 weeks is shown")

    def test_tail_horizons(self):
        t = pd.read_csv(MODEL / "forecast_tail_reliability.csv")
        shown = sorted(int(h) for h in t[(t.target == "ur") & t.show.astype(bool)].horizon.unique())
        self.assertEqual(shown, [3, 6], "the card says the 0.5-point chance is shown at 3 and 6 months only")


if __name__ == "__main__":
    unittest.main()
