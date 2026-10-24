"""Independent layout/run splits and bounded observational rollout collection."""
from dataclasses import asdict
import hashlib
import json
import random
from .dispatch import CongestionPolicy, DistancePolicy, Dispatcher
from .experiments import scenario_hash
from .models import FEATURES, features
from .scenario import ClosureSpec, OrderSpec, Scenario
from .simulation import Simulation


def layout_spec(seed, topology="shelves"):
    rng = random.Random(seed)
    width, height = rng.choice((13, 15, 17)), rng.choice((9, 11))
    if topology == "barrier":
        column = rng.choice((width // 2 - 1, width // 2, width // 2 + 1))
        gaps = rng.sample(range(1, height - 1), 2)
        walls = [(column, y) for y in range(height) if y not in gaps]
    else:
        walls = []
        for x in range(rng.choice((3, 4)), width - 2, 3):
            gap = rng.randrange(2, height - 2)
            walls.extend((x, y) for y in range(2, height - 2) if y != gap)
    geometry = {"width": width, "height": height, "walls": sorted(walls)}
    digest = hashlib.sha256(json.dumps(geometry, sort_keys=True).encode()).hexdigest()
    return {**geometry, "layout_id": digest, "seed": seed, "topology": topology}


def split_manifest(quick=False):
    counts = (3, 1, 1, 1) if quick else (6, 2, 2, 2)
    seeds = {"train": list(range(1000, 1001 if quick else 1002)),
             "validation": list(range(2000, 2001 if quick else 2002)),
             "test": list(range(3000, 3002 if quick else 3020)),
             "ood": list(range(4000, 4002 if quick else 4005))}
    if not quick:
        seeds = {key: [seed + 10000 for seed in values] for key, values in seeds.items()}
    groups = {}
    seen = (set() if quick else {layout["layout_id"] for group in split_manifest(True)["groups"].values()
                                for layout in group["layouts"]})
    starts = (101, 201, 301, 401) if quick else (1101, 1201, 1301, 1401)
    for split, start, count in zip(seeds, starts, counts):
        layouts = []
        for attempt in range(100):
            layout = layout_spec(start + attempt, "barrier" if split == "ood" else "shelves")
            if layout["layout_id"] not in seen:
                layouts.append(layout)
                seen.add(layout["layout_id"])
            if len(layouts) == count:
                break
        if len(layouts) != count:
            raise ValueError("Unable to generate distinct split layouts within budget")
        groups[split] = {"layouts": layouts, "run_seeds": seeds[split]}
    manifest = {"format_version": 1, "mode": "quick-smoke" if quick else "full",
                "horizon": 120 if quick else 180, "groups": groups,
                "collection_policies": ["distance", "congestion", "explore"],
                "demands": {"light": 8, "heavy": 2}, "ood_interval": 1,
                "features": list(FEATURES), "final_test_used_for_selection": False}
    assert_disjoint(manifest)
    return manifest


def assert_disjoint(manifest):
    groups = list(manifest["groups"].items())
    for i, (name, group) in enumerate(groups):
        ids = {g["layout_id"] for g in group["layouts"]}
        if len(ids) != len(group["layouts"]):
            raise ValueError("Duplicate layout within split")
        for other_name, other in groups[i + 1:]:
            if ids & {g["layout_id"] for g in other["layouts"]}:
                raise ValueError(f"Layout leakage: {name}/{other_name}")
            if set(group["run_seeds"]) & set(other["run_seeds"]):
                raise ValueError(f"Run seed leakage: {name}/{other_name}")


def make_scenario(layout, run_seed, interval, horizon, fleet=4):
    rng = random.Random(run_seed)
    width, height = layout["width"], layout["height"]
    walls = tuple(tuple(c) for c in layout["walls"])
    parking = tuple((x, height - 1) for x in range(width) if (x, height - 1) not in walls)[:fleet]
    stations = [(x, y) for x in (1, width - 2) for y in range(1, height - 1)]
    orders = tuple(OrderSpec(f"job-{i:04d}", release, *rng.sample(stations, 2))
                   for i, release in enumerate(range(0, horizon, interval)))
    free = {(x, y) for x in range(width) for y in range(height)} - set(walls) - set(parking) - set(stations)
    closure_cell = rng.choice(sorted(free))
    return Scenario(width, height, walls, parking, orders,
                    (ClosureSpec(closure_cell, horizon // 3, 15),),
                    ((0, horizon // 2, 4),), run_seed, horizon).validate()


class ExplorePolicy:
    name = "explore"

    def __init__(self, seed):
        self.rng = random.Random(seed)

    def score(self, candidate):
        return self.rng.random() * 80


def rollout(scenario, policy):
    dispatcher = Dispatcher(policy)
    sim = Simulation(scenario, record_trace=False)
    while not sim.done:
        dispatcher.dispatch(sim)
        sim.step()
    return sim, dispatcher


def collect(manifest, split, destination):
    rows, summaries, runs = [], [], []
    group = manifest["groups"][split]
    for index, layout in enumerate(group["layouts"]):
        for seed in group["run_seeds"]:
            fleet = 4 if (index + seed) % 2 == 0 else 6
            for demand, interval in manifest["demands"].items():
                scenario = make_scenario(layout, seed, interval, manifest["horizon"], fleet)
                for name in manifest["collection_policies"]:
                    policy = {"distance": DistancePolicy, "congestion": CongestionPolicy,
                              "explore": lambda: ExplorePolicy(seed + index * 100)}[name]()
                    sim, dispatcher = rollout(scenario, policy)
                    run_id = f"{split}-{index}-{seed}-{demand}-{name}"
                    digest = scenario_hash(scenario)
                    run = {"run_id": run_id, "layout_id": layout["layout_id"],
                           "scenario_hash": digest, "policy": name, "seed": seed, "demand": demand}
                    runs.append(run)
                    summaries.append({**run, **sim.summary(), "assigned": len(dispatcher.decisions)})
                    for decision in dispatcher.decisions:
                        job = sim.jobs[decision["job_id"]]
                        assert job["assigned"] == decision["observed_tick"] >= decision["release"]
                        complete = job["completed"]
                        rows.append({**run, "split": split, "robot_id": decision["robot_id"],
                                     "job_id": decision["job_id"], "feature_tick": decision["observed_tick"],
                                     **{key: decision[key] for key in FEATURES},
                                     "status": job["status"], "censored": complete is None,
                                     "duration": complete - job["assigned"] if complete is not None else None,
                                     "observed_lower_bound": sim.tick - job["assigned"]})
                destination.write_text(json.dumps({"runs": runs, "summaries": summaries, "samples": rows}, indent=2) + "\n")
                print(f"Collected {split} layout {index + 1}/{len(group['layouts'])}, seed {seed}, {demand}", flush=True)
    destination.write_text(json.dumps({"runs": runs, "summaries": summaries, "samples": rows}, indent=2) + "\n")
    return rows, summaries


def completed_xy(rows):
    complete = [r for r in rows if not r["censored"]]
    return [[float(r[key]) for key in FEATURES] for r in complete], [float(r["duration"]) for r in complete]
