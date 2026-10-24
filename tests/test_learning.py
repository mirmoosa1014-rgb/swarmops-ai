from dataclasses import asdict, replace
import json
from pathlib import Path
import random
from statistics import mean
import tempfile
import unittest
from swarmops.datasets import assert_disjoint, collect, completed_xy, make_scenario, split_manifest
from swarmops.dispatch import DispatchConfig, DistancePolicy, candidates, match, observe
from swarmops.learning import errors, train_models
from swarmops.models import (FEATURES, DurationModel, LearnedPolicy, base_duration,
                             features, load_model, save_model)
from swarmops.simulation import Simulation


def samples(n=140):
    rng = random.Random(91)
    x = [[rng.randrange(1, 20), rng.randrange(1, 20), 2, rng.randrange(4),
          rng.randrange(4), rng.randrange(20), 4, 2, 2, 100, .1] for _ in range(n)]
    y = [base_duration(row) + 3 + 2 * row[3] for row in x]
    return x, y


class ModelTests(unittest.TestCase):
    def test_linear_learns_known_relationship(self):
        x, y = samples()
        model = DurationModel("linear").fit(x, y)
        self.assertLess(errors(model.predict(x), y)["mae"], .1)
        self.assertGreater(errors([base_duration(row) for row in x], y)["mae"], 5)

    def test_forest_fits_and_is_seeded(self):
        x, y = samples()
        a = DurationModel("forest", trees=8, depth=4, leaf=4).fit(x, y)
        b = DurationModel("forest", trees=8, depth=4, leaf=4).fit(x, y)
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertLess(errors(a.predict(x), y)["mae"], 2)
        self.assertEqual(a.predict(x), DurationModel.from_dict(a.to_dict()).predict(x))

    def test_roundtrip_and_integrity(self):
        x, y = samples()
        for kind in ("linear", "forest"):
            model = DurationModel(kind, trees=4).fit(x, y)
            with tempfile.TemporaryDirectory() as tmp:
                save_model(model, tmp, {"training_samples": len(x)})
                loaded, metadata = load_model(tmp)
                self.assertEqual(model.predict(x), loaded.predict(x))
                self.assertEqual(metadata["training_samples"], len(x))
                (Path(tmp) / "model.json").write_text("{}")
                with self.assertRaises(ValueError):
                    load_model(tmp)

    def test_schema_and_bounds(self):
        x, y = samples()
        model = DurationModel().fit(x, y)
        data = model.to_dict()
        data["features"] = list(reversed(FEATURES))
        with self.assertRaises(ValueError):
            DurationModel.from_dict(data)
        with self.assertRaises(ValueError):
            model.predict([[1]])
        with self.assertRaises(ValueError):
            DurationModel().fit(x[:3], y[:3])
        with self.assertRaises(ValueError):
            DurationModel(depth=99)
        self.assertFalse(set(FEATURES) & {"duration", "completed", "seed", "observed_tick", "job_id", "release"})

    def test_real_predict_batch_and_fallback(self):
        scenario = make_scenario(split_manifest(True)["groups"]["train"]["layouts"][0], 1000, 8, 120)
        batch = candidates(observe(Simulation(scenario)), DispatchConfig())
        class Spy:
            def __init__(self): self.calls = 0
            def predict(self, rows):
                self.calls += 1
                return [base_duration(row) + 7 for row in rows]
        spy = Spy()
        policy = LearnedPolicy(spy)
        match(batch, policy, DispatchConfig())
        self.assertEqual(spy.calls, 1)
        self.assertEqual(policy.prediction_count, len(batch.candidates))
        self.assertEqual(policy.fallbacks, 0)
        class Broken:
            def predict(self, rows): return [float("nan")] * len(rows)
        policy = LearnedPolicy(Broken())
        self.assertEqual(policy.score(batch.candidates[0]), batch.candidates[0].distance_estimate)
        self.assertEqual(policy.fallbacks, 1)
        unsupported = replace(batch.candidates[0], fleet_size=9)
        policy = LearnedPolicy(spy)
        self.assertEqual(policy.score(unsupported), unsupported.distance_estimate)
        self.assertEqual(policy.fallbacks, 1)


class DataTests(unittest.TestCase):
    def test_disjoint_splits_and_overlap_rejection(self):
        modes = [split_manifest(quick) for quick in (True, False)]
        ids = [{layout["layout_id"] for group in m["groups"].values() for layout in group["layouts"]} for m in modes]
        self.assertFalse(ids[0] & ids[1])
        seeds = [{seed for group in m["groups"].values() for seed in group["run_seeds"]} for m in modes]
        self.assertFalse(seeds[0] & seeds[1])
        for quick in (True, False):
            manifest = split_manifest(quick)
            assert_disjoint(manifest)
            manifest["groups"]["test"]["layouts"] = manifest["groups"]["train"]["layouts"][:1]
            with self.assertRaises(ValueError):
                assert_disjoint(manifest)
        manifest = split_manifest(True)
        manifest["groups"]["validation"]["run_seeds"] = [1000]
        with self.assertRaises(ValueError):
            assert_disjoint(manifest)

    def test_censoring_and_feature_time_alignment(self):
        manifest = split_manifest(True)
        manifest["groups"]["train"]["layouts"] = manifest["groups"]["train"]["layouts"][:1]
        manifest["horizon"] = 60
        manifest["collection_policies"] = ["distance"]
        with tempfile.TemporaryDirectory() as tmp:
            rows, summaries = collect(manifest, "train", Path(tmp) / "samples.json")
        self.assertTrue(any(r["censored"] for r in rows))
        for row in rows:
            self.assertLess(row["feature_tick"], 60)
            self.assertEqual(row["duration"] is None, row["censored"])
            if row["duration"] is not None:
                self.assertGreater(row["duration"], 0)
                self.assertLessEqual(row["duration"], row["observed_lower_bound"])
        x, y = completed_xy(rows)
        self.assertEqual(len(y), sum(not r["censored"] for r in rows))
        self.assertEqual(len(x[0]), len(FEATURES))
        self.assertEqual(sum(r["assigned"] for r in summaries), len(rows))

    def test_selection_has_only_training_validation_inputs(self):
        x, y = samples()
        rows = [{**dict(zip(FEATURES, row)), "duration": target, "censored": False}
                for row, target in zip(x, y)]
        with tempfile.TemporaryDirectory() as tmp:
            model, metadata = train_models(rows[:100], rows[100:], Path(tmp))
            self.assertEqual(metadata["training_samples"], 100)
            self.assertEqual(metadata["validation_samples"], 40)
            self.assertEqual(metadata["status"], "frozen-before-final-evaluation")
            self.assertEqual(len(metadata["candidate_validation_scores"]), 3)


if __name__ == "__main__":
    unittest.main()
