from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from swarmops.dispatch import (Candidate, CongestionPolicy, DispatchConfig, Dispatcher,
                              DistancePolicy, candidates, match, observe)
from swarmops.experiments import benchmark, paired_rows, run_policy, scenario_hash
from swarmops.scenario import ClosureSpec, OrderSpec, Scenario, preset
from swarmops.simulation import Simulation


def fixture(**overrides):
    return replace(Scenario(7, 5, (), ((0, 0), (6, 4)),
                           (OrderSpec("old", 0, (1, 0), (2, 0)),
                            OrderSpec("new", 0, (5, 4), (4, 4))), horizon=30), **overrides).validate()


class DispatchTests(unittest.TestCase):
    def test_hand_calculated_features_and_scores(self):
        batch = candidates(observe(Simulation(fixture())), DispatchConfig())
        candidate = next(c for c in batch.candidates if c.robot_id == 0 and c.job_id == "old")
        self.assertEqual((candidate.empty_distance, candidate.loaded_distance), (1, 1))
        self.assertEqual(DistancePolicy().score(candidate), 6)
        self.assertEqual(CongestionPolicy().score(candidate), 6)
        congested = replace(candidate, occupied_route_cells=2, nearby_robots=3)
        self.assertEqual(CongestionPolicy().score(congested), 17)

    def test_matching_no_duplicate_and_nearest(self):
        batch = candidates(observe(Simulation(fixture())), DispatchConfig())
        selected = match(batch, DistancePolicy(), DispatchConfig())
        self.assertEqual([(c.robot_id, c.job_id) for c in selected], [(0, "old"), (1, "new")])
        self.assertEqual(selected, match(batch, DistancePolicy(), DispatchConfig()))

    def test_shared_candidates_for_both_scorers(self):
        batch = candidates(observe(Simulation(fixture())), DispatchConfig())
        seen = []
        class Recorder:
            def __init__(self, policy):
                self.policy = policy
            def score(self, candidate):
                seen.append(candidate)
                return self.policy.score(candidate)
        for policy in (DistancePolicy(), CongestionPolicy()):
            seen.clear()
            match(batch, Recorder(policy), DispatchConfig())
            self.assertEqual(tuple(seen), batch.candidates)

    def test_future_inputs_and_outcomes_hidden(self):
        base = fixture()
        future = replace(base, orders=base.orders + (OrderSpec("secret", 20, (1, 1), (5, 1)),),
                         closures=(ClosureSpec((2, 2), 20, 5),), pauses=((0, 20, 3),))
        view = observe(Simulation(base))
        self.assertEqual(view, observe(Simulation(future)))
        self.assertFalse(hasattr(view, "scenario"))
        with self.assertRaises(FrozenInstanceError):
            view.tick = 12

    def test_cap_oldest_first_and_no_available_robots(self):
        sim = Simulation(fixture())
        batch = candidates(observe(sim), DispatchConfig(candidate_jobs=1))
        self.assertEqual(batch.excluded_by_limit, 1)
        self.assertEqual({c.job_id for c in batch.candidates}, {"new"})  # same release: ID tie
        sim.assign(0, "old"); sim.assign(1, "new")
        self.assertEqual(candidates(observe(sim), DispatchConfig()).candidates, ())

    def test_aging_changes_priority(self):
        batch = candidates(observe(Simulation(fixture(parking=((0, 0),)))), DispatchConfig())
        old, new = (next(c for c in batch.candidates if c.job_id == name) for name in ("old", "new"))
        old = replace(old, release=0, observed_tick=100, empty_distance=20)
        new = replace(new, release=100, observed_tick=100)
        batch = replace(batch, candidates=(old, new))
        self.assertEqual(match(batch, DistancePolicy(), DispatchConfig(aging_weight=0))[0].job_id, "new")
        self.assertEqual(match(batch, DistancePolicy(), DispatchConfig(aging_weight=1))[0].job_id, "old")

    def test_closures_applied_before_scoring_and_paused_excluded(self):
        s = fixture(walls=tuple((3, y) for y in (0, 1, 3, 4)),
                    parking=((0, 0),), orders=(OrderSpec("cross", 0, (1, 0), (5, 0)),),
                    closures=(ClosureSpec((3, 2), 0, 5),))
        sim = Simulation(s)
        dispatcher = Dispatcher(DistancePolicy())
        self.assertEqual(dispatcher.dispatch(sim), ())
        self.assertEqual(dispatcher.audit[-1]["infeasible_pairs"], 1)
        self.assertEqual(sim.closures[0]["activated"], 0)
        sim = Simulation(fixture(pauses=((0, 0, 5),)))
        batch = candidates(observe(sim), DispatchConfig())
        self.assertEqual({c.robot_id for c in batch.candidates}, {1})

    def test_rejected_scores_not_silently_hidden(self):
        class Invalid:
            def score(self, candidate):
                return float("nan")
        with self.assertRaises(ValueError):
            match(candidates(observe(Simulation(fixture())), DispatchConfig()), Invalid(), DispatchConfig())
        for options in ({"candidate_jobs": 0}, {"aging_weight": -1}, {"aging_weight": float("inf")}):
            with self.assertRaises(ValueError):
                DispatchConfig(**options)

    def test_trace_off_does_not_change_dynamics(self):
        first = Simulation(fixture())
        second = Simulation(fixture(), record_trace=False)
        for sim in (first, second):
            dispatcher = Dispatcher(CongestionPolicy())
            while not sim.done:
                dispatcher.dispatch(sim); sim.step()
        self.assertEqual(first.jobs, second.jobs)
        self.assertEqual(first.events, second.events)
        self.assertEqual(second.trace, [])


class ExperimentTests(unittest.TestCase):
    def test_pairing_determinism_and_input_immutability(self):
        scenario = fixture()
        before = scenario_hash(scenario)
        rows = []
        for name in ("distance", "congestion"):
            row, detail = run_policy(scenario, name)
            row.update(layout="fixture", demand="light")
            rows.append(row)
            self.assertEqual(detail["summary"]["completed"], 2)
            self.assertEqual(row["scenario_hash"], before)
        self.assertEqual(paired_rows(rows)[0]["delta_completed"], 0)
        _, repeated = run_policy(scenario, "distance")
        _, first = run_policy(scenario, "distance")
        for key in ("decisions", "candidate_audit", "events", "jobs", "closures"):
            self.assertEqual(first[key], repeated[key])
        self.assertEqual(scenario_hash(scenario), before)
        broken = [{**r} for r in rows]
        broken[1]["scenario_hash"] = "wrong"
        with self.assertRaises(ValueError):
            paired_rows(broken)
        with self.assertRaises(ValueError):
            paired_rows(rows[:1])
        with self.assertRaises(ValueError):
            paired_rows(rows + rows[:1])

    def test_cancel_preserves_completed_run(self):
        original = run_policy
        called = 0
        def interrupted(scenario, policy, config):
            nonlocal called
            called += 1
            if called == 2:
                raise KeyboardInterrupt
            return original(replace(scenario, horizon=1, orders=(), closures=(), pauses=()), policy, config)
        with tempfile.TemporaryDirectory() as tmp:
            with patch("swarmops.experiments.run_policy", side_effect=interrupted):
                with self.assertRaises(KeyboardInterrupt):
                    benchmark(Path(tmp), quick=True)
            manifest = json.loads((Path(tmp) / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "cancelled")
            self.assertEqual(manifest["completed_runs"], 1)
            self.assertTrue((Path(tmp) / "runs.csv").exists())


if __name__ == "__main__":
    unittest.main()
