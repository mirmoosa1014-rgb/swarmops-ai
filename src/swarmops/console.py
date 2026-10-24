"""Thread-safe console runtime around the verified simulator; bounded persistence."""
from dataclasses import asdict, replace
import copy
import csv
import hashlib
import json
from pathlib import Path
from threading import Event, RLock, Thread
from time import monotonic
from . import __version__
from .datasets import make_scenario, split_manifest
from .dispatch import CongestionPolicy, DistancePolicy, Dispatcher
from .experiments import scenario_hash
from .models import LearnedPolicy, load_model
from .planning import astar
from .scenario import Scenario, preset
from .simulation import Simulation

ROOT = Path(__file__).resolve().parents[2]


def validate_console_scenario(value):
    scenario = Scenario.from_json(json.dumps(value))
    if scenario.width > 25 or scenario.height > 25 or len(scenario.orders) > 300 or scenario.horizon > 1000:
        raise ValueError("Console limit: 25×25 cells, 300 jobs and 1,000 ticks")
    free = scenario.free
    for order in scenario.orders:
        if (astar(order.pickup, order.delivery, free) is None or
                not any(astar(home, order.pickup, free) for home in scenario.parking)):
            raise ValueError(f"Job {order.id} is disconnected; open a route before applying")
    return scenario


def console_preset(name, seed):
    if type(seed) is not int or not 0 <= seed <= 1_000_000:
        raise ValueError("Seed must be an integer from 0 to 1,000,000")
    if name == "held-out":
        layout = split_manifest(False)["groups"]["test"]["layouts"][0]
        return make_scenario(layout, seed, 4, 300)
    if name not in ("light", "bottleneck", "closure"):
        raise ValueError("Unknown preset")
    scenario = preset(seed, order_count=48 if name == "bottleneck" else 30,
                      layout="bottleneck" if name == "bottleneck" else "small", horizon=300)
    interval = 2 if name == "bottleneck" else 8 if name == "light" else 4
    return replace(scenario, orders=tuple(replace(o, release=i * interval) for i, o in enumerate(scenario.orders)),
                   closures=scenario.closures if name == "closure" else ()).validate()


class ConsoleEngine:
    def __init__(self, storage, *, threaded=True):
        self.storage = Path(storage)
        self.storage.mkdir(parents=True, exist_ok=True)
        self.lock, self.stop = RLock(), Event()
        self.model, self.metadata = load_model()
        self.speed, self.playing, self.compare, self.selected = 8, False, True, "distance"
        self.preset_name, self.error, self.history, self.heat = "closure", None, [], {}
        self.restored = False
        self.task_cancel = Event()
        self.task = {"status": "idle", "progress": 0, "total": 3, "results": []}
        self.evaluation = {"model_id": None, "counts": []}
        evidence = ROOT / "results/ml-full"
        if (evidence / "manifest.json").exists() and (evidence / "evaluation-runs.csv").exists():
            manifest = json.loads((evidence / "manifest.json").read_text())
            with (evidence / "evaluation-runs.csv").open() as stream:
                rows = [r for r in csv.DictReader(stream) if r["split"] == "test"]
            self.evaluation = {"model_id": manifest["frozen_model_id"], "counts": [
                {"policy": name, "completed": sum(int(r["completed"]) for r in rows if r["policy"] == name)}
                for name in ("distance", "congestion", "learned")]}
        prior_task = self.storage / "last-experiment.json"
        if prior_task.exists() and prior_task.stat().st_size <= 100_000:
            try:
                saved_task = json.loads(prior_task.read_text())
                if isinstance(saved_task.get("results"), list) and len(saved_task["results"]) <= 3:
                    self.task = saved_task
                    if self.task["status"] in ("running", "cancelling"):
                        self.task["status"] = "interrupted"
            except (ValueError, KeyError, TypeError):
                pass
        self.task_thread = None
        scenario, ticks = console_preset("closure", 7), 0
        path = self.storage / "session.json"
        if path.exists():
            try:
                if path.stat().st_size > 2_000_000:
                    raise ValueError("Saved session too large")
                saved = json.loads(path.read_text())
                scenario = validate_console_scenario(saved["scenario"])
                self.selected = saved["policy"] if saved["policy"] in ("distance", "congestion", "learned") else "distance"
                self.speed = min(30, max(1, int(saved.get("speed", 8))))
                self.compare = bool(saved.get("compare", True))
                self.preset_name = saved.get("preset", "imported")
                if saved.get("model_id") != self.metadata["model_id"]:
                    raise ValueError("Saved run uses a different model; restore aborted")
                ticks = saved["tick"]
                if type(ticks) is not int or not 0 <= ticks <= scenario.horizon:
                    raise ValueError("Invalid saved tick")
                self.restored = True
            except (ValueError, KeyError, TypeError, OSError) as exc:
                self.error = f"Saved session could not be restored: {exc}"
                scenario, ticks = console_preset("closure", 7), 0
        self._reset(scenario)
        for _ in range(ticks):
            self._advance()
        self._persist()
        self.thread = Thread(target=self._loop, name="swarmops-clock", daemon=True) if threaded else None
        if self.thread:
            self.thread.start()

    def _policy(self, name):
        return LearnedPolicy(self.model, self.metadata) if name == "learned" else (
            DistancePolicy() if name == "distance" else CongestionPolicy())

    def _reset(self, scenario):
        self.scenario = scenario
        self.sims = [Simulation(scenario), Simulation(scenario)]
        self.dispatchers = [Dispatcher(self._policy(self.selected)), Dispatcher(self._policy("learned"))]
        self.history, self.heat, self.playing = [], {}, False

    def _advance(self):
        if self.sims[0].done:
            self.playing = False
            return
        for sim, dispatcher in zip(self.sims, self.dispatchers):
            dispatcher.dispatch(sim)
            sim.step()
        for robot in self.sims[0].robots:
            key = f"{robot.cell[0]},{robot.cell[1]}"
            self.heat[key] = self.heat.get(key, 0) + 1
        self.history.append({"tick": self.sims[0].tick,
                             "left": self.sims[0].summary()["completed"],
                             "right": self.sims[1].summary()["completed"]})
        if self.sims[0].done:
            self.playing = False

    def _persist(self):
        data = {"version": 1, "scenario": asdict(self.scenario), "tick": self.sims[0].tick,
                "policy": self.selected, "speed": self.speed, "compare": self.compare,
                "preset": self.preset_name, "model_id": self.metadata["model_id"]}
        temporary = self.storage / "session.tmp"
        temporary.write_text(json.dumps(data))
        temporary.replace(self.storage / "session.json")

    def _loop(self):
        while not self.stop.is_set():
            started = monotonic()
            with self.lock:
                if self.playing:
                    try:
                        self._advance()
                        if self.sims[0].tick % 10 == 0 or not self.playing:
                            self._persist()
                    except Exception as exc:
                        self.playing = False
                        self.error = f"Run stopped at tick {self.sims[0].tick}: {type(exc).__name__}: {exc}"
                        (self.storage / "failed-scenario.json").write_text(self.scenario.to_json())
                delay = 1 / self.speed
            self.stop.wait(max(.005, delay - (monotonic() - started)))

    def command(self, data):
        action = data.get("action")
        with self.lock:
            if action == "play":
                self.playing = not self.sims[0].done
            elif action == "pause":
                self.playing = False
            elif action == "step":
                self.playing = False
                self._advance()
            elif action == "speed":
                if type(data.get("value")) is not int or not 1 <= data["value"] <= 30:
                    raise ValueError("Speed must be 1–30 ticks/sec")
                self.speed = data["value"]
            elif action == "compare":
                if type(data.get("value")) is not bool:
                    raise ValueError("Compare must be boolean")
                self.compare = data["value"]
            elif action in ("reset", "preset", "policy", "scenario"):
                scenario = self.scenario
                if action == "preset":
                    scenario = console_preset(data.get("preset"), data.get("seed", 7))
                    self.preset_name = data["preset"]
                elif action == "policy":
                    if data.get("value") not in ("distance", "congestion", "learned"):
                        raise ValueError("Unknown dispatcher")
                    self.selected = data["value"]
                elif action == "scenario":
                    scenario = validate_console_scenario(data.get("scenario"))
                    self.preset_name = "custom"
                self._reset(scenario)
                self.error = None
                self.restored = False
            else:
                raise ValueError("Unknown command")
            if action in ("play", "step"):
                self.restored = False
            self._persist()
            return self.snapshot()

    def snapshot(self):
        with self.lock:
            runs = []
            for sim, dispatcher in zip(self.sims, self.dispatchers):
                runs.append({"policy": dispatcher.policy.name, "summary": sim.summary(),
                             "robots": [asdict(r) for r in sim.robots], "jobs": sim.jobs,
                             "paths": sim.paths, "closures": sim.closures,
                             "events": sim.events[-12:], "model_fallbacks": getattr(dispatcher.policy, "fallbacks", 0)})
            return copy.deepcopy({"revision": __version__, "scenario_hash": scenario_hash(self.scenario),
                    "scenario": asdict(self.scenario), "runs": runs, "playing": self.playing,
                    "speed": self.speed, "compare": self.compare, "preset": self.preset_name,
                    "error": self.error, "restored": self.restored, "history": self.history,
                    "heat": self.heat, "model": self.metadata, "task": self.task,
                    "evaluation": self.evaluation})

    def export(self, kind):
        with self.lock:
            if kind == "scenario":
                return asdict(self.scenario)
            if kind not in ("summary", "trace"):
                raise ValueError("Unknown export")
            return {"revision": __version__, "model_id": self.metadata["model_id"],
                    "scenario_hash": scenario_hash(self.scenario), "scenario": asdict(self.scenario),
                    "runs": [{"policy": d.policy.name, "summary": s.summary(), "closures": s.closures,
                              **({"trace": s.trace, "decisions": d.decisions, "events": s.events} if kind == "trace" else {})}
                             for s, d in zip(self.sims, self.dispatchers)]}

    def start_experiment(self):
        with self.lock:
            if self.task["status"] in ("running", "cancelling"):
                raise ValueError("An experiment is already running")
            self.task_cancel.clear()
            self.task = {"status": "running", "progress": 0, "total": 3, "results": []}
            scenario = self.scenario
            def work():
                try:
                    for name in ("distance", "congestion", "learned"):
                        sim = Simulation(scenario, record_trace=False)
                        dispatcher = Dispatcher(self._policy(name))
                        while not sim.done:
                            if self.task_cancel.is_set():
                                with self.lock:
                                    self.task["status"] = "cancelled"
                                    (self.storage / "last-experiment.json").write_text(json.dumps(self.task))
                                return
                            dispatcher.dispatch(sim)
                            sim.step()
                            if sim.tick % 10 == 0:
                                with self.lock:
                                    self.task["tick"] = sim.tick
                        with self.lock:
                            self.task["results"].append({"policy": name, **sim.summary()})
                            self.task["progress"] += 1
                            (self.storage / "last-experiment.json").write_text(json.dumps(self.task))
                    with self.lock:
                        self.task["status"] = "complete"
                        (self.storage / "last-experiment.json").write_text(json.dumps(self.task, indent=2))
                except Exception as exc:
                    with self.lock:
                        self.task.update(status="failed", error=str(exc))
                        (self.storage / "last-experiment.json").write_text(json.dumps(self.task))
            self.task_thread = Thread(target=work, name="swarmops-experiment", daemon=True)
            self.task_thread.start()
            return self.task

    def cancel_experiment(self):
        with self.lock:
            self.task_cancel.set()
            if self.task["status"] == "running":
                self.task["status"] = "cancelling"
            return self.task

    def close(self):
        self.stop.set()
        self.task_cancel.set()
        for thread in (self.thread, self.task_thread):
            if thread:
                thread.join(timeout=5)
        with self.lock:
            self._persist()
