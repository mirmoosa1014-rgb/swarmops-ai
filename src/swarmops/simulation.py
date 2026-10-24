"""Deterministic integer-tick simulator; no renderer or wall-clock dependency."""
from dataclasses import asdict, dataclass
from time import perf_counter
from . import __version__
from .planning import astar, distance, space_time
from .scenario import Scenario


@dataclass
class Robot:
    id: int
    cell: tuple[int, int]
    home: tuple[int, int]
    state: str = "idle"
    job: str | None = None
    remaining: int = 0
    travel: int = 0
    waiting: int = 0


class Simulation:
    def __init__(self, scenario: Scenario, *, record_trace: bool = True):
        self.scenario = scenario.validate()
        self.record_trace = record_trace
        self.robots = [Robot(i, cell, cell) for i, cell in enumerate(scenario.parking)]
        self.tick = 0
        self.jobs = {o.id: {"spec": asdict(o), "status": "unreleased", "assigned": None,
                            "picked": None, "completed": None, "reason": None}
                     for o in scenario.orders}
        self.closures = [{"spec": asdict(c), "activated": None, "ended": None}
                         for c in scenario.closures]
        self.events = []
        self.trace = []
        self.metrics = {"vertex_violations": 0, "edge_violations": 0, "planning_failures": 0,
                        "stall_events": 0, "recoveries": 0, "planner_seconds": 0.0}
        self.stalled_ticks = 0
        self.in_stall = False
        self.best_distances = {}
        self.yield_until = 0
        self.yield_robot = None
        self.paths = {}
        self._release()
        self._record()

    @property
    def done(self):
        return self.tick >= self.scenario.horizon

    @property
    def free(self):
        blocked = {tuple(c["spec"]["cell"]) for c in self.closures
                   if c["activated"] is not None and c["ended"] is None}
        return self.scenario.free - blocked

    def _release(self):
        for job in self.jobs.values():
            if job["status"] != "unreleased" or job["spec"]["release"] > self.tick:
                continue
            spec = job["spec"]
            # Structural impossibility is distinct from a temporary closure.
            if (astar(tuple(spec["pickup"]), tuple(spec["delivery"]), self.scenario.free) is None
                    or not any(astar(r.home, tuple(spec["pickup"]), self.scenario.free)
                               for r in self.robots)):
                job.update(status="impossible", reason="disconnected")
            else:
                job["status"] = "queued"

    def assign(self, robot_id: int, job_id: str):
        if self.done:
            raise ValueError("Run has ended")
        if type(robot_id) is not int or not 0 <= robot_id < len(self.robots):
            raise ValueError("Unknown robot")
        robot = self.robots[robot_id]
        job = self.jobs.get(job_id)
        if robot.job is not None or job is None or job["status"] != "queued":
            raise ValueError("Assignment requires available robot and queued job")
        if (astar(robot.cell, tuple(job["spec"]["pickup"]), self.free) is None
                or astar(tuple(job["spec"]["pickup"]), tuple(job["spec"]["delivery"]), self.free) is None):
            raise ValueError("Assignment currently disconnected")
        robot.job, robot.state = job_id, "to_pickup"
        job.update(status="assigned", assigned=self.tick)
        self.events.append({"tick": self.tick, "kind": "assignment", "robot": robot_id, "job": job_id})

    def _paused(self, robot):
        return any(i == robot.id and start <= self.tick < start + duration
                   for i, start, duration in self.scenario.pauses)

    def _target(self, robot):
        if robot.job is None:
            return robot.home
        spec = self.jobs[robot.job]["spec"]
        return tuple(spec["delivery"] if robot.state == "to_delivery" else spec["pickup"])

    def _closures(self):
        occupied = {r.cell for r in self.robots}
        for closure in self.closures:
            spec = closure["spec"]
            if closure["activated"] is not None:
                if closure["ended"] is None and self.tick >= closure["activated"] + spec["duration"]:
                    closure["ended"] = self.tick
                continue
            if self.tick >= spec["requested"] and tuple(spec["cell"]) not in occupied:
                closure["activated"] = self.tick
                self.events.append({"tick": self.tick, "kind": "closure_activated", "cell": spec["cell"]})

    def step(self):
        if self.done:
            raise ValueError("Run has ended")
        self._closures()
        if self.stalled_ticks in (8, 16):
            self.yield_robot = (self.tick // 8) % len(self.robots)
            self.yield_until = self.tick + 8
            self.events.append({"tick": self.tick, "kind": "yield_attempt", "robot": self.yield_robot})
        horizon = self.scenario.planning_horizon
        # Reserve a safe stationary fallback for EVERY robot before planning.
        paths = {r.id: [r.cell] * (horizon + 1) for r in self.robots}
        start = perf_counter()
        offset = (self.tick // 8) % len(self.robots)
        priority = self.robots[offset:] + self.robots[:offset]
        for robot in priority:
            if self._paused(robot) or robot.state in ("loading", "unloading"):
                continue
            vertices, edges = set(), set()
            for other, path in paths.items():
                if other == robot.id:
                    continue
                vertices.update((cell, t) for t, cell in enumerate(path))
                edges.update((path[t - 1], path[t], t) for t in range(1, len(path)))
            target = robot.home if robot.id == self.yield_robot and self.tick < self.yield_until else self._target(robot)
            plan = space_time(robot.cell, target, self.free, vertices, edges, horizon)
            if plan is None:
                self.metrics["planning_failures"] += 1
            else:
                paths[robot.id] = plan
        self.metrics["planner_seconds"] += perf_counter() - start
        previous = [r.cell for r in self.robots]
        upcoming = [paths[r.id][1] for r in self.robots]
        vertex = len(upcoming) != len(set(upcoming))
        edge = any(previous[i] == upcoming[j] and previous[j] == upcoming[i]
                   for i in range(len(previous)) for j in range(i + 1, len(previous)))
        self.metrics["vertex_violations"] += int(vertex)
        self.metrics["edge_violations"] += int(edge)
        assert not vertex and not edge, f"Collision at seed={self.scenario.seed}, tick={self.tick}"
        productive = False
        for robot, nxt in zip(self.robots, upcoming):
            assert nxt in self.free and abs(nxt[0] - robot.cell[0]) + abs(nxt[1] - robot.cell[1]) <= 1
            moved = nxt != robot.cell
            robot.travel += int(moved)
            robot.waiting += int(not moved and robot.job is not None)
            robot.cell = nxt
            if robot.job is not None:
                key = (robot.job, robot.state)
                remaining = distance(robot.cell, self._target(robot))
                best = self.best_distances.get(key, float("inf"))
                productive |= remaining < best
                self.best_distances[key] = min(best, remaining)
            if self._paused(robot):
                continue
            if robot.state in ("loading", "unloading"):
                robot.remaining -= 1
                productive = True
                if robot.remaining == 0:
                    job = self.jobs[robot.job]
                    if robot.state == "loading":
                        job["picked"] = self.tick + 1
                        robot.state = "to_delivery"
                    else:
                        assert job["picked"] is not None and job["completed"] is None
                        job.update(status="completed", completed=self.tick + 1)
                        self.events.append({"tick": self.tick + 1, "kind": "delivered", "job": robot.job})
                        robot.job, robot.state = None, "idle"
            elif robot.job is not None and robot.cell == self._target(robot):
                robot.state = "loading" if robot.state == "to_pickup" else "unloading"
                robot.remaining = self.scenario.service_ticks
                productive = True
        active = any(r.job is not None for r in self.robots)
        self.stalled_ticks = self.stalled_ticks + 1 if active and not productive else 0
        if self.stalled_ticks >= 24 and not self.in_stall:
            self.metrics["stall_events"] += 1
            self.in_stall = True
            self.events.append({"tick": self.tick + 1, "kind": "fleet_stalled",
                                "jobs": [r.job for r in self.robots if r.job]})
        if self.in_stall and productive:
            self.metrics["recoveries"] += 1
            self.in_stall = False
        self.paths = paths
        self.tick += 1
        self._release()
        self._assert_lifecycle()
        self._record()

    def _assert_lifecycle(self):
        assigned = [r.job for r in self.robots if r.job is not None]
        assert len(assigned) == len(set(assigned))
        for job in self.jobs.values():
            if job["completed"] is not None:
                assert job["assigned"] <= job["picked"] <= job["completed"]
                assert job["status"] == "completed"

    def _record(self):
        if not self.record_trace:
            return
        self.trace.append({"tick": self.tick, "robots": [asdict(r) for r in self.robots],
                           "jobs": {key: job["status"] for key, job in self.jobs.items()}})

    def summary(self):
        released = [j for j in self.jobs.values() if j["spec"]["release"] <= self.tick]
        completed = [j for j in released if j["status"] == "completed"]
        latencies = sorted(j["completed"] - j["spec"]["release"] for j in completed)
        return {"simulation_revision": __version__, "tick": self.tick, "seed": self.scenario.seed,
                "released": len(released), "completed": len(completed),
                "completion_fraction": len(completed) / len(released) if released else None,
                "backlog": sum(j["status"] not in ("completed", "impossible") for j in released),
                "impossible": sum(j["status"] == "impossible" for j in released),
                "censored_assigned": sum(j["assigned"] is not None and j["completed"] is None for j in released),
                "mean_latency": sum(latencies) / len(latencies) if latencies else None,
                "p95_latency": latencies[max(0, (95 * len(latencies) + 99) // 100 - 1)] if latencies else None,
                "travel_ticks": sum(r.travel for r in self.robots),
                "waiting_ticks": sum(r.waiting for r in self.robots), **self.metrics}
