"""Pure fixtures for efficiency admission and conservative measured selection.

These timings/digests are synthetic and qualify no model, backend or hardware.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError
from hashlib import sha256
import json
import unittest

from hosted.experimental.cellivane_seed import efficiency as policy


def reports(*, gpu29=.90, gpu29_threads8=.85):
    identity = {"model_sha256": policy.MODEL_SHA256, "backend_tree_sha256": "b" * 64,
                "corpus_sha256": "c" * 64, "source_sha256": "d" * 64}
    output = []
    for profile, wall in zip(policy.PROFILES, (1., gpu29, gpu29_threads8)):
        rounds = []
        for index in range(2):
            rounds.append({"index": index, "samples": [
                {"case_id": f"case-{case:02}", "repeat": repeat, "wall_s": wall,
                 "text_sha256": sha256(f"fixture-{case}-{repeat}".encode()).hexdigest()}
                for case in range(14) for repeat in range(4)]})
        output.append({"profile": profile.record(), "identity": dict(identity), "outcome": "PASS",
                       "resource_guard_passed": True, "rounds": rounds})
    return output


def comparison(result, name):
    return next(row for row in result["comparisons"] if row["profile"]["name"] == name)


def disable_third(rows):
    rows[2]["outcome"] = "FAIL"
    rows[2]["resource_guard_passed"] = False
    rows[2]["rounds"] = []


class ProfileTests(unittest.TestCase):
    def test_profiles_are_frozen_distinct_and_control_fa_without_claiming_observation(self):
        self.assertEqual([(p.num_gpu, p.num_thread) for p in policy.PROFILES], [(21, 4), (29, 4), (29, 8)])
        self.assertEqual(len({p.identity_sha256 for p in policy.PROFILES}), 3)
        for profile in policy.PROFILES:
            with self.assertRaises(FrozenInstanceError):
                profile.num_thread = 8
            self.assertEqual(profile.environment, {"OLLAMA_KV_CACHE_TYPE": "f16"})
            self.assertEqual(profile.unset_environment, ("OLLAMA_FLASH_ATTENTION",))
            self.assertEqual(profile.ollama_options["num_ctx"], 2048)
            self.assertIn("requested", profile.record()["scope"])
            self.assertIs(policy.get_profile(profile.name), profile)
        record = policy.REFERENCE.record()
        record["environment"]["OLLAMA_KV_CACHE_TYPE"] = "q4_0"
        record["unset_environment"].clear()
        self.assertEqual(policy.REFERENCE.environment, {"OLLAMA_KV_CACHE_TYPE": "f16"})
        self.assertEqual(policy.REFERENCE.unset_environment, ("OLLAMA_FLASH_ATTENTION",))

    def test_unsupported_profile_combinations_bool_and_unknown_options_rejected(self):
        for kwargs in ({"name": "gpu30", "num_gpu": 30, "num_thread": 4},
                       {"name": "reference", "num_gpu": 21, "num_thread": 8},
                       {"name": "gpu29", "num_gpu": True, "num_thread": 4},
                       {"name": "gpu29", "num_gpu": 29, "num_thread": 4, "slots": True},
                       {"name": "gpu29", "num_gpu": 29, "num_thread": 4, "temperature": 0.0},
                       {"name": "gpu29", "num_gpu": 29, "num_thread": 4, "flash_attention": "on"},
                       {"name": "gpu29", "num_gpu": 29, "num_thread": 4, "kv_cache_type": "q8_0"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                policy.EfficiencyProfile(**kwargs)
        with self.assertRaises(TypeError):
            policy.EfficiencyProfile("reference", 21, 4, unsupported=True)
        with self.assertRaises(ValueError):
            policy.get_profile(True)


class AdmissionTests(unittest.TestCase):
    def forecast(self, profile=policy.GPU29, **overrides):
        values = {"model_bytes": policy.MODEL_BYTES, "available_ram_bytes": 20 * 1024 ** 3,
                  "free_vram_bytes": 6 * 1024 ** 3}
        values.update(overrides)
        return policy.admission_forecast(profile, **values)

    def test_integer_ceil_and_exact_one_byte_admission_boundaries(self):
        plan = self.forecast()
        numerator = 8 * 5_027_783_488 * 115
        estimate = numerator // 3700 + bool(numerator % 3700)
        self.assertEqual(plan["incremental_layer_estimate_bytes"], estimate)
        self.assertEqual(plan["vram_forecast_bytes"], 3_100_597_288 + estimate + 268_435_456)
        self.assertEqual(plan["ram_required_bytes"], 5_027_783_488 + 7 * 1024 ** 3)
        exact = self.forecast(available_ram_bytes=plan["ram_required_bytes"],
                              free_vram_bytes=plan["vram_required_free_bytes"])
        self.assertTrue(exact["admitted"])
        for key, value, reason in (("available_ram_bytes", plan["ram_required_bytes"] - 1, "insufficient-available-ram"),
                                   ("free_vram_bytes", plan["vram_required_free_bytes"] - 1, "insufficient-free-vram")):
            blocked = self.forecast(**{key: value})
            self.assertFalse(blocked["admitted"])
            self.assertIn(reason, blocked["reasons"])
            self.assertEqual(blocked["profile_sha256"], policy.GPU29.identity_sha256)
        self.assertIn("not-reservation-or-fit-proof", plan["scope"])

    def test_reference_uses_no_increment_and_failed_admission_does_not_downgrade(self):
        self.assertEqual(self.forecast(policy.REFERENCE)["incremental_layer_estimate_bytes"], 0)
        plan = self.forecast(free_vram_bytes=0, available_ram_bytes=0)
        self.assertFalse(plan["admitted"])
        self.assertEqual(len(plan["reasons"]), 2)
        self.assertEqual(plan["profile_sha256"], policy.GPU29.identity_sha256)

    def test_model_pin_and_unsigned_exact_byte_types(self):
        for key, value in (("model_bytes", True), ("model_bytes", policy.MODEL_BYTES - 1),
                           ("available_ram_bytes", -1), ("available_ram_bytes", 2 ** 63),
                           ("free_vram_bytes", True), ("free_vram_bytes", float("nan")),
                           ("free_vram_bytes", 8.0)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.forecast(**{key: value})


class SelectionTests(unittest.TestCase):
    def test_both_balanced_rounds_choose_fastest_qualifying_profile(self):
        values = reports()
        saved = deepcopy(values)
        result = policy.choose_profile(values[::-1])
        self.assertTrue(result["eligible"])
        self.assertEqual(result["selected_profile"]["name"], "gpu29-threads8")
        self.assertEqual(result["reason"], "measured-balanced-gain")
        self.assertEqual(values, saved)
        for row in result["comparisons"]:
            self.assertTrue(row["qualifies"])
            self.assertEqual(len(row["rounds"]), 2)
            self.assertEqual(len(row["overall"]["cases"]), 14)
        result["identity"]["model_sha256"] = "0" * 64
        result["selected_profile"]["environment"].clear()
        self.assertEqual(values, saved)
        self.assertEqual(policy.GPU29_THREADS8.environment, {"OLLAMA_KV_CACHE_TYPE": "f16"})
        json.dumps(policy.choose_profile(values), allow_nan=False)

    def test_tie_uses_declared_profile_order_not_report_order(self):
        values = reports(gpu29=.9, gpu29_threads8=.9)
        self.assertEqual(policy.choose_profile(values[::-1])["selected_profile"]["name"], "gpu29")

    def test_exact_five_percent_overall_boundary(self):
        for wall, selected in ((.95, "gpu29"), (.9500001, "reference")):
            values = reports(gpu29=wall)
            disable_third(values)
            self.assertEqual(policy.choose_profile(values)["selected_profile"]["name"], selected)

    def test_one_good_round_cannot_hide_second_round_regression(self):
        values = reports(gpu29=.7)
        disable_third(values)
        for row in values[1]["rounds"][1]["samples"]:
            row["wall_s"] = 1.01
        result = policy.choose_profile(values)
        self.assertEqual(result["selected_profile"]["name"], "reference")
        self.assertTrue(comparison(result, "gpu29")["overall"]["p50_gain_passed"])
        self.assertFalse(comparison(result, "gpu29")["rounds"][1]["qualifies"])

    def test_tail_regression_is_rejected_despite_fast_median_and_equal_text(self):
        values = reports(gpu29=.8)
        disable_third(values)
        for round_ in values[1]["rounds"]:
            for row in round_["samples"][:4]:
                row["wall_s"] = 1.050001
        result = policy.choose_profile(values)
        candidate = comparison(result, "gpu29")
        self.assertTrue(candidate["overall"]["qualifies"])
        self.assertIn("p95-regression", candidate["reasons"])
        self.assertEqual(result["selected_profile"]["name"], "reference")
        for round_ in values[1]["rounds"]:
            for row in round_["samples"][:4]:
                row["wall_s"] = 1.05
        self.assertEqual(policy.choose_profile(values)["selected_profile"]["name"], "gpu29")

    def test_case_regression_cannot_hide_below_aggregate_p95(self):
        values = reports(gpu29=.8)
        disable_third(values)
        for round_ in values[1]["rounds"]:
            for row in round_["samples"][:2]:
                row["wall_s"] = 1.42
        result = policy.choose_profile(values)
        candidate = comparison(result, "gpu29")
        self.assertLess(candidate["overall"]["p95_latency_ratio"], 1)
        self.assertFalse(candidate["overall"]["case_regression_guard_passed"])
        self.assertGreater(candidate["overall"]["cases"][0]["latency_ratio"], 1.10)
        self.assertEqual(result["selected_profile"]["name"], "reference")
        for round_ in values[1]["rounds"]:
            for row in round_["samples"][:2]:
                row["wall_s"] = 1.4
        self.assertEqual(policy.choose_profile(values)["selected_profile"]["name"], "gpu29")

    def test_overall_p50_gain_cannot_replace_case_balanced_gain(self):
        values = reports()
        disable_third(values)
        for round_index in range(2):
            for index in range(56):
                high_case = index // 4 >= 7
                values[0]["rounds"][round_index]["samples"][index]["wall_s"] = 10. if high_case else 1.
                values[1]["rounds"][round_index]["samples"][index]["wall_s"] = 9.2 if high_case else 1.
        result = policy.choose_profile(values)
        candidate = comparison(result, "gpu29")
        self.assertTrue(candidate["overall"]["p50_gain_passed"])
        self.assertFalse(candidate["overall"]["balanced_case_gain_passed"])
        self.assertEqual(result["selected_profile"]["name"], "reference")

    def test_extreme_finite_inputs_cannot_emit_nonfinite_comparison(self):
        values = reports(gpu29=1e-308)
        disable_third(values)
        result = policy.choose_profile(values)
        self.assertEqual(result["selected_profile"]["name"], "gpu29")
        json.dumps(result, allow_nan=False)
        for round_ in values[1]["rounds"]:
            for row in round_["samples"]:
                row["wall_s"] = 1e-320
        with self.assertRaises(ValueError):
            policy.choose_profile(values)

    def test_exact_output_hash_mismatch_blocks_a_fast_candidate(self):
        values = reports(gpu29=.8)
        disable_third(values)
        values[1]["rounds"][1]["samples"][-1]["text_sha256"] = "0" * 64
        result = policy.choose_profile(values)
        self.assertEqual(result["selected_profile"]["name"], "reference")
        self.assertIn("output-mismatch", comparison(result, "gpu29")["reasons"])

    def test_resource_guard_and_reference_failure_are_execution_ineligible(self):
        values = reports(gpu29=.8)
        disable_third(values)
        values[1]["resource_guard_passed"] = False
        result = policy.choose_profile(values)
        self.assertEqual(result["selected_profile"]["name"], "reference")
        self.assertIn("candidate-not-qualified", comparison(result, "gpu29")["reasons"])
        values[0].update(outcome="FAIL", resource_guard_passed=False, rounds=[])
        result = policy.choose_profile(values)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason"], "reference-not-qualified")
        self.assertFalse(any(row["qualifies"] for row in result["comparisons"]))

    def test_model_source_corpus_backend_identity_rebinding_rejected(self):
        for key in ("model_sha256", "source_sha256", "corpus_sha256", "backend_tree_sha256"):
            values = reports()
            values[1]["identity"][key] = "0" * 64
            with self.subTest(key=key), self.assertRaises(ValueError):
                policy.choose_profile(values)

    def test_missing_duplicate_case_and_repeat_grid_rejected(self):
        for mutation in (lambda rows: rows.pop(),
                         lambda rows: rows.__setitem__(1, deepcopy(rows[0])),
                         lambda rows: rows[0].__setitem__("repeat", True),
                         lambda rows: rows[0].__setitem__("case_id", "different-case")):
            values = reports()
            mutation(values[1]["rounds"][0]["samples"])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                policy.choose_profile(values)

    def test_round_case_catalog_and_order_are_bound(self):
        for mutation in (lambda values: values[1]["rounds"][0].__setitem__("index", True),
                         lambda values: values[1]["rounds"].reverse(),
                         lambda values: values[1]["rounds"].pop()):
            values = reports()
            mutation(values)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                policy.choose_profile(values)
        values = reports()
        for round_ in values[1]["rounds"]:
            for row in round_["samples"]:
                row["case_id"] = row["case_id"].replace("case-", "other-")
        with self.assertRaises(ValueError):
            policy.choose_profile(values)

    def test_unknown_keys_bool_nonfinite_and_unsafe_profile_records_rejected(self):
        mutations = [lambda values: values[1].__setitem__("unknown", 1),
                     lambda values: values[1].__setitem__("resource_guard_passed", 1),
                     lambda values: values[1]["profile"].__setitem__("slots", True),
                     lambda values: values[1]["profile"].__setitem__("unset_environment", ("OLLAMA_FLASH_ATTENTION",)),
                     lambda values: values[1]["profile"]["environment"].__setitem__("OLLAMA_FLASH_ATTENTION", "on"),
                     lambda values: values[1]["identity"].__setitem__("attested", True)]
        for wall in (True, 0, -1, 3601, float("nan"), float("inf")):
            mutations.append(lambda values, wall=wall: values[1]["rounds"][0]["samples"][0].__setitem__("wall_s", wall))
        for mutation in mutations:
            values = reports()
            mutation(values)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                policy.choose_profile(values)

    def test_missing_and_duplicate_profiles_or_nonreference_baseline_rejected(self):
        values = reports()
        for rows in (values[:2], [values[0], values[1], deepcopy(values[1])], tuple(values)):
            with self.subTest(rows=type(rows)), self.assertRaises(ValueError):
                policy.choose_profile(rows)
        with self.assertRaises(ValueError):
            policy.choose_profile(values, reference=policy.GPU29)


if __name__ == "__main__":
    unittest.main()
