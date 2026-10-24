"""Headless policy demo and exports. FIFO retained for core regression checks."""
import argparse
import json
from pathlib import Path
from .scenario import Scenario, preset
from .simulation import Simulation


def demo(sim):
    while not sim.done:
        for robot in sim.robots:
            if robot.job is not None:
                continue
            for key, job in sim.jobs.items():
                if job["status"] == "queued":
                    try:
                        sim.assign(robot.id, key)
                    except ValueError:
                        continue
                    break
        sim.step()
    return sim


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--layout", choices=("small", "medium", "bottleneck"), default="small")
    parser.add_argument("--scenario", type=Path)
    parser.add_argument("--policy", choices=("fifo", "distance", "congestion", "learned"), default="distance")
    parser.add_argument("--output", type=Path, default=Path("runs/demo"))
    args = parser.parse_args()
    scenario = Scenario.from_json(args.scenario.read_text()) if args.scenario else preset(args.seed, layout=args.layout)
    sim = Simulation(scenario)
    dispatcher = None
    if args.policy == "fifo":
        demo(sim)
    else:
        from .dispatch import Dispatcher, POLICIES
        if args.policy == "learned":
            from .models import LearnedPolicy
            dispatcher = Dispatcher(LearnedPolicy())
        else:
            dispatcher = Dispatcher(POLICIES[args.policy]())
        while not sim.done:
            dispatcher.dispatch(sim)
            sim.step()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, data in (("summary", sim.summary()), ("trace", sim.trace),
                       ("events", sim.events), ("closures", sim.closures)):
        (args.output / f"{name}.json").write_text(json.dumps(data, indent=2))
    (args.output / "scenario.json").write_text(scenario.to_json())
    if dispatcher is not None:
        identity = getattr(dispatcher.policy, "metadata", {}).get("model_id")
        (args.output / "dispatch.json").write_text(json.dumps({"policy": args.policy,
                    "model_id": identity, "model_fallbacks": getattr(dispatcher.policy, "fallbacks", 0),
                    "decisions": dispatcher.decisions, "audit": dispatcher.audit}, indent=2))
    print(json.dumps(sim.summary(), indent=2))


if __name__ == "__main__":
    main()
