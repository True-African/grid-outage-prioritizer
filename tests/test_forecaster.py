import tempfile
import unittest
from pathlib import Path

import pandas as pd

from forecaster import evaluate_holdout, forecast_next_24, load_history, train
from generate_data import generate_all


class ForecasterTest(unittest.TestCase):
    def test_generate_train_forecast_and_evaluate(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            generate_all(data_dir, seed=7)
            history = load_history(data_dir / "grid_history.csv")
            self.assertGreaterEqual(len(history), 180 * 24)
            for factor in ["voltage_drop_index", "feeder_congestion_index", "maintenance_flag", "neighbor_outage_reports"]:
                self.assertIn(factor, history.columns)
            model = train(history)
            forecast = forecast_next_24(model, history)
            self.assertEqual(len(forecast), 24)
            for col in ["timestamp", "p_outage", "p_low", "p_high", "expected_duration_min", "risk_minutes", "top_risk_factor", "risk_explanation"]:
                self.assertIn(col, forecast.columns)
            self.assertTrue(((forecast["p_outage"] >= 0) & (forecast["p_outage"] <= 1)).all())
            metrics, worst = evaluate_holdout(history)
            self.assertIn("brier_score", metrics)
            self.assertLessEqual(metrics["brier_score"], 1.0)
            self.assertIsInstance(worst, pd.DataFrame)


if __name__ == "__main__":
    unittest.main()
