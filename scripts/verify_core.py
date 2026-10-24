"""Reproduce section-one safety evidence; not a dispatcher comparison."""
import json
from pathlib import Path
from time import perf_counter
from swarmops.__main__ import demo
from swarmops.scenario import preset
from swarmops.simulation import Simulation


def main():
    records = []
    start = perf_counter()
    for layout in ("small", "medium", "bottleneck"):
        for robots in (4, 8, 12):
            for seed in range(5):
                sim = demo(Simulation(preset(seed, robots=robots, order_count=24,
                                             horizon=200, layout=layout)))
                records.append({"layout": layout, "robots": robots, **sim.summary()})
    result = {"purpose": "Core safety smoke sweep, provisional FIFO assignment; not ML evaluation",
              "elapsed_seconds": perf_counter() - start, "runs": records}
    output = Path("results/core-verification.json")
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"runs": len(records), "ticks": sum(r["tick"] for r in records),
                      "completed": sum(r["completed"] for r in records),
                      "vertex_violations": sum(r["vertex_violations"] for r in records),
                      "edge_violations": sum(r["edge_violations"] for r in records),
                      "elapsed_seconds": result["elapsed_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
