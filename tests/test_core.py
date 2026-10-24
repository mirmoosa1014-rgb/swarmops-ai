import json
import random
import unittest
from dataclasses import replace
from swarmops.planning import astar, neighbors, space_time
from swarmops.scenario import ClosureSpec, OrderSpec, Scenario, preset
from swarmops.simulation import Simulation
from swarmops.__main__ import demo


def small(**overrides):
    return replace(Scenario(5, 5, (), ((0, 0),),
                           (OrderSpec("a", 0, (1, 0), (3, 0)),), horizon=40), **overrides).validate()


class PlanningTests(unittest.TestCase):
    def test_astar_shortest_and_valid(self):
        free = small().free - {(2, 0), (2, 1)}
        path = astar((0, 0), (4, 0), free)
        self.assertEqual(len(path) - 1, 8)
        self.assertTrue(all(b in neighbors(a) for a, b in zip(path, path[1:])))
        self.assertTrue(set(path) <= free)

    def test_disconnected(self):
        self.assertIsNone(astar((0, 0), (2, 0), {(0, 0), (2, 0)}))

    def test_reservations(self):
        vertices = {((1, 0), 1), ((2, 0), 2)}
        edges = {((1, 0), (0, 0), 1)}
        path = space_time((0, 0), (3, 0), small().free, vertices, edges, 6)
        self.assertEqual(len(path), 7)
        self.assertTrue(all((c, t) not in vertices for t, c in enumerate(path)))
        self.assertTrue(all((path[t], path[t-1], t) not in edges for t in range(1, 7)))

    def test_goal_occupancy(self):
        path = space_time((0, 0), (1, 0), small().free, {((1, 0), 3)}, set(), 5)
        self.assertNotEqual(path[3], (1, 0))

    def test_search_budget(self):
        self.assertIsNone(space_time((0, 0), (4, 4), small().free, set(), set(), 5, 1))


class ScenarioTests(unittest.TestCase):
    def test_roundtrip(self):
        s = preset()
        self.assertEqual(s, Scenario.from_json(s.to_json()))

    def test_seed(self):
        self.assertEqual(preset(1), preset(1))
        self.assertNotEqual(preset(1).orders, preset(2).orders)

    def test_invalid_imports(self):
        for text in ('{}', '[]', 'null', '{', '{"width": "bad"}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Scenario.from_json(text)
        with self.assertRaises(ValueError):
            small(width=4000)
        with self.assertRaises(ValueError):
            small(parking=((0, 0), (0, 0)))
        with self.assertRaises(ValueError):
            small(orders=(OrderSpec("a", 0, (False, 0), (1, 0)),))


class SimulationTests(unittest.TestCase):
    def test_lifecycle_and_service(self):
        sim = Simulation(small())
        sim.assign(0, "a")
        while sim.jobs["a"]["completed"] is None:
            sim.step()
        job = sim.jobs["a"]
        self.assertEqual(job["picked"], 3)
        self.assertEqual(job["completed"], 7)
        self.assertEqual(sim.robots[0].travel, 3)
        with self.assertRaises(ValueError):
            sim.assign(0, "a")

    def test_no_orders_and_end(self):
        sim = demo(Simulation(small(orders=(), horizon=3)))
        self.assertIsNone(sim.summary()["mean_latency"])
        self.assertEqual(sim.tick, 3)
        with self.assertRaises(ValueError):
            sim.step()

    def test_release_and_duplicate_assignment(self):
        sim = Simulation(small(parking=((0, 0), (0, 1)),
                               orders=(OrderSpec("a", 2, (1, 0), (3, 0)),)))
        with self.assertRaises(ValueError):
            sim.assign(0, "a")
        sim.step(); sim.step()
        sim.assign(0, "a")
        with self.assertRaises(ValueError):
            sim.assign(1, "a")

    def test_impossible_and_censoring(self):
        sim = Simulation(small(walls=tuple((2, y) for y in range(5))))
        self.assertEqual(sim.summary()["impossible"], 1)
        sim = Simulation(small(horizon=1))
        sim.assign(0, "a"); sim.step()
        self.assertEqual(sim.summary()["censored_assigned"], 1)
        self.assertEqual(sim.summary()["backlog"], 1)

    def test_closure_deferral_and_duration(self):
        sim = Simulation(small(orders=(), closures=(ClosureSpec((0, 0), 0, 2),)))
        sim.step()
        self.assertIsNone(sim.closures[0]["activated"])
        sim = Simulation(small(closures=(ClosureSpec((1, 0), 0, 2),)))
        sim.step()
        self.assertNotIn((1, 0), sim.free)
        sim.step(); sim.step()
        self.assertEqual(sim.closures[0]["ended"], 2)
        self.assertIn((1, 0), sim.free)

    def test_pause(self):
        sim = Simulation(small(pauses=((0, 0, 3),)))
        sim.assign(0, "a")
        for _ in range(3):
            sim.step()
            self.assertEqual(sim.robots[0].cell, (0, 0))
        sim.step()
        self.assertEqual(sim.robots[0].cell, (1, 0))

    def test_head_on_corridor_safely_stalls(self):
        walls = tuple((x, y) for x in range(5) for y in range(3) if y != 1)
        s = Scenario(5, 3, walls, ((0, 1), (4, 1)),
                     (OrderSpec("a", 0, (1, 1), (4, 1)),
                      OrderSpec("b", 0, (3, 1), (0, 1))), horizon=60)
        sim = Simulation(s)
        sim.assign(0, "a"); sim.assign(1, "b")
        while not sim.done:
            sim.step()
        self.assertEqual(sim.summary()["completed"], 0)
        self.assertGreater(sim.summary()["stall_events"], 0)
        self.assertEqual(sim.summary()["vertex_violations"], 0)
        self.assertEqual(sim.summary()["edge_violations"], 0)

    def test_determinism_and_action_replay(self):
        first = demo(Simulation(preset(horizon=100, order_count=8)))
        second = Simulation(first.scenario)
        actions = [e for e in first.events if e["kind"] == "assignment"]
        while not second.done:
            for a in actions:
                if a["tick"] == second.tick:
                    second.assign(a["robot"], a["job"])
            second.step()
        self.assertEqual(first.trace, second.trace)
        self.assertEqual(first.events, second.events)
        self.assertEqual(first.scenario.orders, second.scenario.orders)

    def test_intersection_station_parking_multiseed(self):
        for seed in range(8):
            sim = demo(Simulation(preset(seed, horizon=140, order_count=12)))
            with self.subTest(seed=seed):
                self.assertEqual(sim.summary()["vertex_violations"], 0)
                self.assertEqual(sim.summary()["edge_violations"], 0)
                self.assertGreater(sim.summary()["completed"], 0)
                self.assertEqual(sim.summary()["released"], 12)
                for frame in sim.trace:
                    positions = [tuple(r["cell"]) for r in frame["robots"]]
                    self.assertEqual(len(positions), len(set(positions)))


if __name__ == "__main__":
    unittest.main()
