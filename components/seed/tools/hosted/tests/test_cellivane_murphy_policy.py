"""Behavioral boundaries for a pure session-cost policy; no engine is run."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "hosted/experimental"))
from cellivane_murphy_policy import baseline, choose


def round_cost(none_p=1, none_g=2, murphy_p=3, murphy_g=1):
    return {"none": {"preparation_s": none_p, "request_wall_s": [none_g, none_g]},
            "murphy": {"preparation_s": murphy_p, "request_wall_s": [murphy_g, murphy_g]}}


class SessionCostPolicyTests(unittest.TestCase):
    def test_preparation_cost_changes_the_choice_with_expected_session_length(self):
        rounds = [round_cost(), round_cost()]
        short, long = choose(rounds, 1), choose(rounds, 10)
        self.assertEqual(short["selected_mode"], "none")
        self.assertEqual(long["selected_mode"], "murphy")
        self.assertEqual(long["rounds"][0]["none"]["estimated_session_s"], 21)
        self.assertEqual(long["rounds"][0]["murphy"]["estimated_session_s"], 13)
        self.assertEqual(long["reason"], "consistent-session-savings")

    def test_exact_five_percent_margin_qualifies_but_equal_cost_does_not(self):
        tied = choose([round_cost(0, 20, 0, 19), round_cost(0, 40, 0, 38)], 1)
        self.assertEqual(tied["selected_mode"], "murphy")
        equal = choose([round_cost(0, 20, 0, 20)] * 2, 1)
        self.assertEqual(equal["selected_mode"], "none")
        self.assertFalse(equal["rounds"][0]["qualifies"])
        insufficient = choose([round_cost(0, 20, 0, 19.000001)] * 2, 1)
        self.assertEqual(insufficient["selected_mode"], "none")

    def test_one_good_round_cannot_hide_a_bad_round_or_average_into_acceptance(self):
        result = choose([round_cost(0, 100, 0, 1), round_cost(0, 2, 0, 3)], 10)
        self.assertEqual([row["qualifies"] for row in result["rounds"]], [True, False])
        self.assertEqual(result["selected_mode"], "none")
        self.assertEqual(result["reason"], "insufficient-consistent-savings")
        self.assertTrue(result["eligible"])

    def test_mean_uses_both_requests_and_round_indices_remain_ordered(self):
        record = round_cost(5, 10, 6, 2)
        record["none"]["request_wall_s"] = [2, 6]
        record["murphy"]["request_wall_s"] = [1, 3]
        result = choose([record, round_cost()], 2)
        self.assertEqual(result["rounds"][0]["none"]["mean_request_s"], 4)
        self.assertEqual(result["rounds"][0]["none"]["estimated_session_s"], 13)
        self.assertEqual(result["rounds"][0]["murphy"]["estimated_session_s"], 10)
        self.assertEqual([row["index"] for row in result["rounds"]], [0, 1])

    def test_exact_output_shape_and_json_primitives(self):
        value = choose([round_cost(), round_cost()], 1024)
        self.assertEqual(set(value), {"schema_version", "policy", "expected_requests", "margin_percent", "eligible",
                                      "selected_mode", "reason", "rounds", "scope"})
        self.assertEqual(value["policy"], "murphy-session-cost-v1")
        self.assertEqual(value["scope"], "fixed-calibration-corpus-cost-estimate")
        for row in value["rounds"]:
            self.assertEqual(set(row), {"index", "none", "murphy", "qualifies"})
            self.assertEqual(set(row["none"]), {"preparation_s", "mean_request_s", "estimated_session_s"})
            self.assertIs(type(row["qualifies"]), bool)
        self.assertEqual(json.loads(json.dumps(value, allow_nan=False)), value)

    def test_expected_count_rejects_bool_float_none_and_out_of_bounds(self):
        for value in (True, False, 1.0, None, "10", 0, -1, 1025, 10 ** 1000):
            with self.subTest(value=repr(value)[:40]):
                with self.assertRaises(ValueError):
                    choose([round_cost(), round_cost()], value)
                with self.assertRaises(ValueError):
                    baseline(value, "no-calibration")

    def test_missing_unknown_and_wrong_container_shapes_rejected(self):
        malformed = [None, (), [], [round_cost()], [round_cost()] * 3,
                     [dict(round_cost(), extra=1), round_cost()],
                     [{"none": round_cost()["none"]}, round_cost()]]
        for value in malformed:
            with self.subTest(value=repr(value)[:80]), self.assertRaises(ValueError):
                choose(value, 1)
        for mode in ({}, dict(round_cost()["none"], extra=1),
                     {"preparation_s": 0, "request_wall_s": (1, 2)},
                     {"preparation_s": 0, "request_wall_s": [1]},
                     {"preparation_s": 0, "request_wall_s": [1, 2, 3]}):
            value = round_cost()
            value["none"] = mode
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                choose([value, round_cost()], 1)

    def test_seconds_reject_bool_nonfinite_negative_and_excessive(self):
        for field in ("preparation_s", "request_wall_s"):
            for bad in (True, False, None, "1", float("nan"), float("inf"), -float("inf"), -1, 3600.001, 10 ** 1000):
                value = round_cost()
                value["murphy"][field] = bad if field == "preparation_s" else [1, bad]
                with self.subTest(field=field, value=repr(bad)[:40]), self.assertRaises(ValueError):
                    choose([round_cost(), value], 10)
        value = round_cost()
        value["none"]["request_wall_s"] = [0, 1]
        with self.assertRaises(ValueError):
            choose([value, round_cost()], 10)
        self.assertEqual(choose([round_cost(0, 3600, 0, 3600)] * 2, 1024)["selected_mode"], "none")

    def test_result_and_input_are_independent_and_each_call_is_fresh(self):
        rounds = [round_cost(), round_cost()]
        original = copy.deepcopy(rounds)
        first = choose(rounds, 10)
        self.assertEqual(rounds, original)
        rounds[0]["none"]["request_wall_s"][0] = 3000
        self.assertEqual(first["rounds"][0]["none"]["mean_request_s"], 2)
        first["rounds"][0]["murphy"]["preparation_s"] = 2000
        self.assertEqual(choose(original, 10)["rounds"][0]["murphy"]["preparation_s"], 3)
        first["rounds"].clear()
        self.assertEqual(len(choose(original, 10)["rounds"]), 2)

    def test_baseline_reasons_are_explicit_and_unknown_or_none_never_inferred(self):
        for reason in ("no-calibration", "identity-mismatch", "host-profile-mismatch", "source-mismatch",
                       "calibration-expired", "output-mismatch", "legacy-no-host"):
            result = baseline(1, reason)
            self.assertFalse(result["eligible"])
            self.assertEqual(result["selected_mode"], "none")
            self.assertEqual(result["reason"], reason)
            self.assertEqual(result["rounds"], [])
            self.assertEqual(set(result), set(choose([round_cost(), round_cost()], 1)))
        for reason in (None, True, "", "consistent-session-savings", "unknown"):
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                baseline(1, reason)
        changed = baseline(1, "no-calibration")
        changed["rounds"].append({})
        self.assertEqual(baseline(1, "no-calibration")["rounds"], [])


if __name__ == "__main__":
    unittest.main()
