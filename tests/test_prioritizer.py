import unittest

import pandas as pd

from prioritizer import plan


class PrioritizerTest(unittest.TestCase):
    def setUp(self):
        self.forecast = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-04-23", periods=24, freq="h"),
                "p_outage": [0.2] * 24,
                "expected_duration_min": [90] * 24,
                "risk_minutes": [18] * 24,
            }
        )
        self.appliances = [
            {
                "name": "Critical load",
                "category": "critical",
                "watts_avg": 100,
                "start_up_spike_w": 120,
                "revenue_if_running_rwf_per_h": 2000,
            },
            {
                "name": "Comfort load",
                "category": "comfort",
                "watts_avg": 100,
                "start_up_spike_w": 100,
                "revenue_if_running_rwf_per_h": 1500,
            },
            {
                "name": "Luxury load",
                "category": "luxury",
                "watts_avg": 100,
                "start_up_spike_w": 80,
                "revenue_if_running_rwf_per_h": 5000,
            },
        ]
        self.business = {
            "name": "test",
            "backup_limit_w": 200,
            "risk_threshold": 0.1,
            "appliances": ["Critical load", "Comfort load", "Luxury load"],
        }

    def test_critical_kept_before_luxury_even_when_luxury_has_more_revenue(self):
        result = plan(self.forecast, self.appliances, self.business)
        first_hour = result[result["timestamp"] == result["timestamp"].iloc[0]]
        status = dict(zip(first_hour["appliance"], first_hour["status"]))
        self.assertEqual(status["Critical load"], "ON")
        self.assertEqual(status["Comfort load"], "ON")
        self.assertEqual(status["Luxury load"], "OFF")

    def test_low_risk_keeps_all_appliances_on(self):
        low_forecast = self.forecast.copy()
        low_forecast["p_outage"] = 0.01
        low_forecast["risk_minutes"] = 0.9
        result = plan(low_forecast, self.appliances, self.business)
        self.assertTrue((result["status"] == "ON").all())


if __name__ == "__main__":
    unittest.main()

