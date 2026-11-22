"""ROI model tests. Run:  python -m unittest discover -s tests -v"""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_roi.roi import (  # noqa: E402
    UseCase,
    break_even_automation_rate,
    calculate,
    priority_score,
    scenarios,
    sensitivity,
)


def base_case(**overrides) -> UseCase:
    data = dict(
        name="t",
        tasks_per_month=1000,
        minutes_per_task_manual=6,   # $6 manual cost per task at $60/h
        loaded_hourly_cost=60,
        automation_rate=0.5,
        llm_cost_per_task=0.10,
        infra_cost_per_month=500,
        build_cost=20_000,
        ramp_months=0,
        horizon_months=12,
        discount_rate_annual=0.0,
    )
    data.update(overrides)
    return UseCase(**data)


class Economics(unittest.TestCase):
    def test_steady_state_numbers(self):
        r = calculate(base_case())
        # benefits: 1000 tasks * 50% * $6 = $3000; run: 1000 * 0.10 + 500 = $600
        self.assertAlmostEqual(r.steady_state_benefit, 3000)
        self.assertAlmostEqual(r.steady_state_run_cost, 600)
        self.assertAlmostEqual(r.steady_state_net, 2400)
        self.assertAlmostEqual(r.manual_cost_per_task, 6)

    def test_undiscounted_npv_equals_net_value(self):
        r = calculate(base_case())
        self.assertAlmostEqual(r.npv, r.net_value)
        self.assertAlmostEqual(r.net_value, 2400 * 12 - 20_000)

    def test_payback_month(self):
        r = calculate(base_case())
        self.assertEqual(r.payback_month, 9)  # 20,000 / 2,400 = 8.33 -> month 9

    def test_no_payback_when_never_profitable(self):
        r = calculate(base_case(automation_rate=0.05))
        self.assertIsNone(r.payback_month)
        self.assertLess(r.npv, 0)

    def test_discounting_lowers_npv(self):
        undiscounted = calculate(base_case()).npv
        discounted = calculate(base_case(discount_rate_annual=0.12)).npv
        self.assertLess(discounted, undiscounted)

    def test_ramp_delays_benefits(self):
        fast = calculate(base_case(ramp_months=0))
        slow = calculate(base_case(ramp_months=6))
        self.assertLess(slow.npv, fast.npv)
        self.assertGreaterEqual(slow.payback_month, fast.payback_month)

    def test_errors_create_rework_cost(self):
        clean = calculate(base_case())
        sloppy = calculate(base_case(error_rate_agent=0.10, rework_minutes=30))
        self.assertLess(sloppy.npv, clean.npv)

    def test_assist_rate_adds_benefit(self):
        without = calculate(base_case())
        with_assist = calculate(base_case(assist_rate=0.3, assist_time_saving=0.5))
        self.assertGreater(with_assist.npv, without.npv)


class BreakEven(unittest.TestCase):
    def test_break_even_is_where_npv_is_zero(self):
        uc = base_case()
        rate = break_even_automation_rate(uc)
        self.assertIsNotNone(rate)
        npv = calculate(replace(uc, automation_rate=rate), with_break_even=False).npv
        self.assertAlmostEqual(npv, 0, delta=1.0)

    def test_unreachable_break_even(self):
        self.assertIsNone(break_even_automation_rate(base_case(build_cost=10_000_000)))

    def test_zero_when_already_profitable_at_zero(self):
        # no build cost and no fixed costs: any automation pays
        uc = base_case(build_cost=0, infra_cost_per_month=0, llm_cost_per_task=0)
        self.assertEqual(break_even_automation_rate(uc), 0.0)


class Analysis(unittest.TestCase):
    def test_sensitivity_sorted_by_swing(self):
        rows = sensitivity(base_case())
        swings = [r["swing"] for r in rows]
        self.assertEqual(swings, sorted(swings, reverse=True))
        self.assertIn("automation_rate", {r["param"] for r in rows})

    def test_scenarios_are_ordered(self):
        s = scenarios(base_case())
        self.assertLess(s["pessimistic"].npv, s["base"].npv)
        self.assertLess(s["base"].npv, s["optimistic"].npv)


class Validation(unittest.TestCase):
    def test_rejects_bad_rates(self):
        with self.assertRaises(ValueError):
            UseCase.from_dict({**base_case().to_dict(), "automation_rate": 1.5})

    def test_rejects_automation_plus_assist_over_one(self):
        with self.assertRaises(ValueError):
            UseCase.from_dict({**base_case().to_dict(), "automation_rate": 0.7, "assist_rate": 0.5})

    def test_rejects_unknown_fields(self):
        with self.assertRaises(ValueError):
            UseCase.from_dict({**base_case().to_dict(), "autmation_rate": 0.5})


class Prioritization(unittest.TestCase):
    def test_score_range(self):
        best = {k: 5 for k in ("business_value", "feasibility", "data_readiness", "risk", "strategic_fit")}
        worst = {k: 1 for k in best}
        self.assertEqual(priority_score(best), 100.0)
        self.assertEqual(priority_score(worst), 20.0)

    def test_missing_or_out_of_range(self):
        with self.assertRaises(ValueError):
            priority_score({"business_value": 5})
        with self.assertRaises(ValueError):
            priority_score({k: 6 for k in ("business_value", "feasibility", "data_readiness", "risk", "strategic_fit")})


if __name__ == "__main__":
    unittest.main()
