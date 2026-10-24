"""Shared current-state observations, candidates, and deterministic matching.

Policy scorers receive candidates only: no Simulation, schedules or outcomes.
"""
from dataclasses import asdict, dataclass
from math import isfinite
from time import perf_counter
from typing import Protocol
from .planning import Cell, astar, distance, neighbors
from .simulation import Simulation


@dataclass(frozen=True)
class RobotView:
    id: int
    cell: Cell
    available: bool


@dataclass(frozen=True)
class JobView:
    id: str
    release: int
    pickup: Cell
    delivery: Cell


@dataclass(frozen=True)
class Observation:
    tick: int
    free: frozenset[Cell]
    robots: tuple[RobotView, ...]
    queued: tuple[JobView, ...]
    service_ticks: int
    active_jobs: int


def observe(sim: Simulation) -> Observation:
    # Apply only currently eligible closure requests before making decisions.
    # step() repeats this idempotently; future schedules never enter the view.
    sim._closures()
    return Observation(sim.tick, frozenset(sim.free),
                       tuple(RobotView(r.id, r.cell, r.job is None and not sim._paused(r))
                             for r in sim.robots),
                       tuple(sorted((JobView(key, j["spec"]["release"], tuple(j["spec"]["pickup"]),
                                                   tuple(j["spec"]["delivery"]))
                                     for key, j in sim.jobs.items() if j["status"] == "queued"),
                                    key=lambda j: (j.release, j.id))),
                       sim.scenario.service_ticks,
                       sum(r.job is not None for r in sim.robots))


@dataclass(frozen=True)
class DispatchConfig:
    candidate_jobs: int = 32
    aging_weight: float = 0.1

    def __post_init__(self):
        if type(self.candidate_jobs) is not int or not 1 <= self.candidate_jobs <= 256:
            raise ValueError("candidate_jobs must be 1–256")
        if not isfinite(self.aging_weight) or not 0 <= self.aging_weight <= 100:
            raise ValueError("aging_weight must be finite and between 0 and 100")


@dataclass(frozen=True)
class Candidate:
    robot_id: int
    job_id: str
    release: int
    observed_tick: int
    empty_distance: int
    loaded_distance: int
    service_ticks: int
    occupied_route_cells: int
    nearby_robots: int
    queue_length: int
    fleet_size: int
    available_robots: int
    active_jobs: int
    free_cells: int = 0
    narrow_fraction: float = 0.0

    @property
    def age(self):
        return self.observed_tick - self.release

    @property
    def distance_estimate(self):
        return max(1, self.empty_distance) + max(1, self.loaded_distance) + 2 * self.service_ticks


@dataclass(frozen=True)
class CandidateBatch:
    candidates: tuple[Candidate, ...]
    considered_jobs: int
    excluded_by_limit: int
    infeasible_pairs: int


def candidates(view: Observation, config: DispatchConfig) -> CandidateBatch:
    available = tuple(r for r in view.robots if r.available)
    selected = view.queued[:config.candidate_jobs]
    if not available or not selected:
        return CandidateBatch((), len(selected), max(0, len(view.queued) - len(selected)), 0)
    cache = {}

    def path(start, goal):
        key = (start, goal)
        if key not in cache:
            cache[key] = astar(start, goal, view.free)
        return cache[key]

    narrow = sum(sum(n in view.free for n in neighbors(c)) <= 2 for c in view.free) / len(view.free)
    result, infeasible = [], 0
    for job in selected:
        loaded = path(job.pickup, job.delivery)
        for robot in available:
            empty = path(robot.cell, job.pickup)
            if empty is None or loaded is None:
                infeasible += 1
                continue
            route = set(empty[1:]) | set(loaded)
            others = tuple(r.cell for r in view.robots if r.id != robot.id)
            result.append(Candidate(robot.id, job.id, job.release, view.tick,
                                    len(empty) - 1, len(loaded) - 1, view.service_ticks,
                                    sum(c in route for c in others),
                                    sum(any(distance(c, p) <= 1 for p in route) for c in others),
                                    len(view.queued), len(view.robots), len(available), view.active_jobs,
                                    len(view.free), narrow))
    return CandidateBatch(tuple(result), len(selected), max(0, len(view.queued) - len(selected)), infeasible)


class Policy(Protocol):
    name: str

    def score(self, candidate: Candidate) -> float: ...


class DistancePolicy:
    name = "distance"

    def score(self, candidate: Candidate) -> float:
        return float(candidate.distance_estimate)


class CongestionPolicy:
    name = "congestion"

    def score(self, candidate: Candidate) -> float:
        return float(candidate.distance_estimate + 4 * candidate.occupied_route_cells
                     + candidate.nearby_robots)


def match(batch: CandidateBatch, policy: Policy, config: DispatchConfig):
    ranked = []
    scores = (policy.score_many(batch.candidates) if hasattr(policy, "score_many") else
              [policy.score(c) for c in batch.candidates])
    if len(scores) != len(batch.candidates):
        raise ValueError("Policy score count does not match candidates")
    for candidate, raw_score in zip(batch.candidates, scores):
        score = raw_score - config.aging_weight * candidate.age
        if not isfinite(score):
            raise ValueError("Policy returned nonfinite score")
        ranked.append((score, candidate.release, candidate.robot_id, candidate.job_id, candidate))
    used_robots, used_jobs, assignments = set(), set(), []
    for *_, candidate in sorted(ranked, key=lambda row: row[:4]):
        if candidate.robot_id in used_robots or candidate.job_id in used_jobs:
            continue
        used_robots.add(candidate.robot_id)
        used_jobs.add(candidate.job_id)
        assignments.append(candidate)
    return tuple(assignments)


class Dispatcher:
    def __init__(self, policy: Policy, config: DispatchConfig | None = None):
        self.policy = policy
        self.config = config or DispatchConfig()
        self.audit = []
        self.decisions = []
        self.candidate_seconds = 0.0
        self.scoring_seconds = 0.0

    def dispatch(self, sim: Simulation):
        if sim.done:
            raise ValueError("Cannot dispatch after run ends")
        start = perf_counter()
        view = observe(sim)
        batch = candidates(view, self.config)
        self.candidate_seconds += perf_counter() - start
        start = perf_counter()
        assignments = match(batch, self.policy, self.config)
        self.scoring_seconds += perf_counter() - start
        for candidate in assignments:
            # Do not silently swallow an unexpected rejected assignment.
            sim.assign(candidate.robot_id, candidate.job_id)
            self.decisions.append(asdict(candidate))
        self.audit.append({"tick": view.tick, "queued": len(view.queued),
                           "available_robots": sum(r.available for r in view.robots),
                           "considered_jobs": batch.considered_jobs,
                           "excluded_by_limit": batch.excluded_by_limit,
                           "infeasible_pairs": batch.infeasible_pairs,
                           "feasible_pairs": len(batch.candidates), "assigned": len(assignments)})
        return assignments


POLICIES = {"distance": DistancePolicy, "congestion": CongestionPolicy}
