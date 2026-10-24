"""Paired development benchmarks; final held-out ML evaluation comes later."""
import argparse
import csv
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from statistics import mean, stdev
from time import perf_counter
from .dispatch import DispatchConfig, Dispatcher, POLICIES
from .scenario import preset
from .simulation import Simulation


def scenario_hash(scenario):
    return hashlib.sha256(scenario.to_json().encode()).hexdigest()


def run_policy(scenario, policy_name, config=None):
    dispatcher = Dispatcher(POLICIES[policy_name](), config)
    sim = Simulation(scenario, record_trace=False)
    before = scenario_hash(scenario)
    start = perf_counter()
    while not sim.done:
        dispatcher.dispatch(sim)
        sim.step()
    if scenario_hash(scenario) != before:
        raise AssertionError("Exogenous scenario mutated")
    row = {"policy": policy_name, "scenario_hash": before, **sim.summary(),
           "candidate_seconds": dispatcher.candidate_seconds,
           "scoring_seconds": dispatcher.scoring_seconds,
           "elapsed_seconds": perf_counter() - start,
           "assignments": len(dispatcher.decisions),
           "infeasible_pair_ticks": sum(a["infeasible_pairs"] for a in dispatcher.audit),
           "candidate_limit_excluded_job_ticks": sum(a["excluded_by_limit"] for a in dispatcher.audit)}
    detail = {"summary": row, "dispatch_config": asdict(dispatcher.config),
              "decisions": dispatcher.decisions, "candidate_audit": dispatcher.audit,
              "events": sim.events, "closures": sim.closures, "jobs": sim.jobs}
    return row, detail


def paired_rows(rows):
    groups = {}
    for row in rows:
        key = (row["layout"], row["demand"], row["seed"])
        group = groups.setdefault(key, {})
        if row["policy"] in group:
            raise ValueError("Duplicate policy run")
        group[row["policy"]] = row
    pairs = []
    for (layout, demand, seed), group in sorted(groups.items()):
        if set(group) != set(POLICIES):
            raise ValueError("Missing policy in pair")
        base, other = group["distance"], group["congestion"]
        if any(base[key] != other[key] for key in ("scenario_hash", "tick", "released")):
            raise ValueError("Mismatched exogenous inputs or horizon")
        pair = {"layout": layout, "demand": demand, "seed": seed,
                "scenario_hash": base["scenario_hash"]}
        for metric in ("completed", "completion_fraction", "backlog", "mean_latency", "p95_latency",
                       "waiting_ticks", "travel_ticks", "stall_events"):
            pair[f"delta_{metric}"] = (other[metric] - base[metric]
                                        if other[metric] is not None and base[metric] is not None else None)
        pairs.append(pair)
    return pairs


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def report(rows, pairs):
    lines = ["# Development dispatcher comparison", "",
             "Congestion minus distance policy; same scenario hash and horizon within each pair.",
             "These are development scenarios, not an untouched final test set or ML results.", "",
             "| Layout | Demand | Paired seeds | Mean completed: distance / congestion | Mean completion delta ± sample SD | Mean latency delta* |",
             "|---|---|---:|---:|---:|---:|"]
    for layout, demand in sorted({(p["layout"], p["demand"]) for p in pairs}):
        group = [p for p in pairs if (p["layout"], p["demand"]) == (layout, demand)]
        deltas = [p["delta_completed"] for p in group]
        means = [mean(r["completed"] for r in rows if r["layout"] == layout
                      and r["demand"] == demand and r["policy"] == name) for name in POLICIES]
        latency = [p["delta_mean_latency"] for p in group if p["delta_mean_latency"] is not None]
        latency_text = f"{mean(latency):.2f}" if latency else "N/A"
        deviation = f"{stdev(deltas):.2f}" if len(deltas) > 1 else "N/A"
        lines.append(f"| {layout} | {demand} | {len(group)} | {means[0]:.2f} / {means[1]:.2f} | "
                     f"{mean(deltas):.2f} ± {deviation} | {latency_text} |")
    lines += ["", "*Completed-only latency: interpret with completion fraction/backlog in runs.csv.",
              "A lower latency can reflect preferential completion of easy jobs. SD describes paired",
              "variation, not a confidence interval or proof of statistical significance.", "",
              f"Recorded collision violations: {sum(r['vertex_violations'] + r['edge_violations'] for r in rows)}.",
              "Planner, candidate construction, and scoring wall times are reported separately.",
              "Closure request schedules match; actual activation times may differ with occupancy.",
              "Infeasible pairs and jobs excluded by the shared candidate cap are logged per tick.",
              "Heuristic constants are fixed; no tuning against these results was performed."]
    return "\n".join(lines) + "\n"


def benchmark(output, quick=False):
    output.mkdir(parents=True, exist_ok=True)
    config = DispatchConfig()
    mode = {"layouts": ["small", "bottleneck"] if quick else ["small", "medium", "bottleneck"],
            "seeds": list(range(3 if quick else 5)), "horizon": 160 if quick else 200,
            "robots": 4, "split": "development-only", "dispatch_config": asdict(config)}
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(Path(__file__).parent.glob("*.py"))}
    manifest = {"config": mode, "source_hashes": sources, "status": "running"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    rows = []
    try:
        for layout in mode["layouts"]:
            for demand, interval in (("light", 8), ("heavy", 2)):
                for seed in mode["seeds"]:
                    count = (mode["horizon"] - 1) // interval + 1
                    scenario = preset(seed, robots=mode["robots"], order_count=count,
                                      horizon=mode["horizon"], layout=layout)
                    scenario = replace(scenario, orders=tuple(replace(o, release=i * interval)
                                                              for i, o in enumerate(scenario.orders))).validate()
                    name = f"{layout}-{demand}-{seed}"
                    (output / f"{name}-scenario.json").write_text(scenario.to_json())
                    # Alternate execution order to reduce systematic timing bias.
                    names = tuple(POLICIES) if seed % 2 == 0 else tuple(reversed(POLICIES))
                    for policy in names:
                        row, detail = run_policy(scenario, policy, config)
                        row.update(layout=layout, demand=demand)
                        rows.append(row)
                        (output / f"{name}-{policy}.json").write_text(json.dumps(detail, indent=2) + "\n")
                        write_csv(output / "runs.csv", rows)
                    print(f"Finished pair: {name}", flush=True)
        pairs = paired_rows(rows)
        write_csv(output / "paired.csv", pairs)
        (output / "report.md").write_text(report(rows, pairs))
        manifest.update(status="complete", runs=len(rows), pairs=len(pairs))
    except KeyboardInterrupt:
        manifest.update(status="cancelled", completed_runs=len(rows))
        raise
    except Exception:
        manifest.update(status="failed", completed_runs=len(rows))
        raise
    finally:
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return rows, pairs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("runs/comparison"))
    args = parser.parse_args()
    # Fresh output avoids mixing stale run files with a new experiment manifest.
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Output directory must be new or empty")
    benchmark(args.output, args.quick)


if __name__ == "__main__":
    main()
