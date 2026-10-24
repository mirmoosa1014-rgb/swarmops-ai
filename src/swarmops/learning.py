"""Bounded, reproducible local collection → fit → freeze → held-out evaluation."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import random
from statistics import mean, stdev
from time import perf_counter
from .datasets import collect, completed_xy, make_scenario, rollout, split_manifest
from .dispatch import CongestionPolicy, DistancePolicy
from .experiments import scenario_hash, write_csv
from .models import (DEFAULT_MODEL, FEATURES, DurationModel, LearnedPolicy, base_duration,
                     load_model, save_model)


def errors(predictions, y):
    if not y:
        return {"n": 0, "mae": None, "bias": None}
    residual = [p - t for p, t in zip(predictions, y)]
    return {"n": len(y), "mae": mean(abs(e) for e in residual), "bias": mean(residual)}


def train_models(train_rows, validation_rows, output):
    x, y = completed_xy(train_rows)
    vx, vy = completed_xy(validation_rows)
    if len(vy) < 12:
        raise ValueError("Not enough validation completions")
    settings = [("linear", {}), ("forest", {"trees": 16, "depth": 3, "leaf": 12}),
                ("forest", {"trees": 24, "depth": 5, "leaf": 8})]
    fitted, scores = [], []
    for kind, config in settings:
        start = perf_counter()
        model = DurationModel(kind, **config).fit(x, y)
        metric = errors(model.predict(vx), vy)
        scores.append({"kind": kind, "config": model.to_dict()["config"],
                       **metric, "fit_seconds": perf_counter() - start})
        fitted.append(model)
    selected = min(range(len(scores)), key=lambda i: (scores[i]["mae"], i))
    model = fitted[selected]
    # Refit neither on validation nor test. Selection ends here.
    metadata = {"selected_model": scores[selected], "candidate_validation_scores": scores,
                "distance_validation": errors([base_duration(row) for row in vx], vy),
                "training_samples": len(y), "validation_samples": len(vy),
                "training_censored": sum(r["censored"] for r in train_rows),
                "split_method": "entire disjoint layouts and run seeds",
                "implementation": "project-standard-library-regressors-v1",
                "status": "frozen-before-final-evaluation", "python": platform.python_version(),
                "feature_ranges": {key: [min(row[j] for row in x), max(row[j] for row in x)]
                                   for j, key in enumerate(FEATURES)}}
    identity = save_model(model, output / "model", metadata)
    (output / "selection.json").write_text(json.dumps({**metadata, "model_id": identity}, indent=2) + "\n")
    # Validation-only permutation importance. No causal interpretation.
    original = errors(model.predict(vx), vy)["mae"]
    rng = random.Random(23)
    importance = []
    for j, key in enumerate(FEATURES):
        column = [row[j] for row in vx]
        rng.shuffle(column)
        changed = [row[:] for row in vx]
        for row, value in zip(changed, column):
            row[j] = value
        importance.append({"feature": key, "permuted_mae_increase": errors(model.predict(changed), vy)["mae"] - original})
    write_csv(output / "validation-importance.csv", importance)
    return model, {**metadata, "model_id": identity}


def evaluate(manifest, model, metadata, output):
    runs, predictions = [], []
    for split in ("test", "ood"):
        group = manifest["groups"][split]
        for index, layout in enumerate(group["layouts"]):
            for seed in group["run_seeds"]:
                loads = {"stress": manifest["ood_interval"]} if split == "ood" else manifest["demands"]
                for demand, interval in loads.items():
                    scenario = make_scenario(layout, seed, interval, manifest["horizon"], 8 if split == "ood" else 4)
                    case = f"{split}-{index}-{seed}-{demand}"
                    digest = scenario_hash(scenario)
                    policies = [DistancePolicy(), CongestionPolicy(), LearnedPolicy(model, metadata)]
                    shift = seed % 3
                    policies = policies[shift:] + policies[:shift]
                    for policy in policies:
                        start = perf_counter()
                        sim, dispatcher = rollout(scenario, policy)
                        assert scenario_hash(scenario) == digest
                        row = {"split": split, "layout_id": layout["layout_id"], "demand": demand,
                               "case": case, "policy": policy.name, "scenario_hash": digest,
                               **sim.summary(), "model_id": metadata["model_id"] if policy.name == "learned" else None,
                               "model_fallbacks": getattr(policy, "fallbacks", 0),
                               "model_predictions": getattr(policy, "prediction_count", 0),
                               "inference_seconds": getattr(policy, "predict_seconds", 0),
                               "candidate_seconds": dispatcher.candidate_seconds,
                               "scoring_seconds": dispatcher.scoring_seconds,
                               "elapsed_seconds": perf_counter() - start}
                        runs.append(row)
                        for decision in dispatcher.decisions:
                            job = sim.jobs[decision["job_id"]]
                            x = [float(decision[key]) for key in FEATURES]
                            target = None if job["completed"] is None else job["completed"] - job["assigned"]
                            predictions.append({"split": split, "case": case, "policy": policy.name,
                                                "layout_id": layout["layout_id"], "seed": seed,
                                                "job_id": decision["job_id"], "feature_tick": decision["observed_tick"],
                                                **{key: decision[key] for key in FEATURES},
                                                "duration": target, "censored": target is None,
                                                "latency": None if target is None else job["completed"] - job["spec"]["release"],
                                                "prediction": model.predict([x])[0],
                                                "distance_prediction": base_duration(x)})
                        # Retain all outcomes and current-state decision features, not just successes.
                        detail = {"summary": row, "jobs": sim.jobs, "closures": sim.closures,
                                  "assignments": dispatcher.decisions, "events": sim.events,
                                  "candidate_audit": dispatcher.audit}
                        (output / "evaluation" / f"{case}-{policy.name}.json").write_text(json.dumps(detail, indent=2) + "\n")
                        write_csv(output / "evaluation-runs.csv", runs)
                    print(f"Evaluated {case}", flush=True)
    write_csv(output / "predictions.csv", predictions)
    paired = []
    for case in sorted({r["case"] for r in runs}):
        group = {r["policy"]: r for r in runs if r["case"] == case}
        assert len(group) == 3
        assert len({(r["scenario_hash"], r["tick"], r["released"]) for r in group.values()}) == 1
        learned = group["learned"]
        for baseline in ("distance", "congestion"):
            pair = {"case": case, "split": learned["split"], "layout_id": learned["layout_id"],
                    "seed": learned["seed"], "demand": learned["demand"], "baseline": baseline}
            for metric in ("completed", "completion_fraction", "backlog", "mean_latency", "p95_latency",
                           "waiting_ticks", "travel_ticks"):
                a, b = learned[metric], group[baseline][metric]
                pair[f"delta_{metric}"] = a - b if a is not None and b is not None else None
            paired.append(pair)
    write_csv(output / "paired.csv", paired)
    return runs, predictions, paired


def distribution_shift(train_rows, predictions):
    result = []
    for split in ("test", "ood"):
        for policy in ("distance", "congestion", "learned"):
            rows = [r for r in predictions if r["split"] == split and r["policy"] == policy]
            for key in FEATURES:
                training = [r[key] for r in train_rows]  # includes censored assignments
                values = [r[key] for r in rows]
                low, high = min(training), max(training)
                result.append({"split": split, "policy": policy, "feature": key,
                               "train_mean": mean(training), "deployment_mean": mean(values) if values else None,
                               "training_min": low, "training_max": high,
                               "outside_training_range_fraction": mean(v < low or v > high for v in values) if values else None})
    return result


def result_report(manifest, metadata, summaries, runs, predictions, paired, elapsed):
    metrics = {}
    for split in ("test", "ood"):
        for policy in ("distance", "congestion", "learned"):
            complete = [p for p in predictions if p["split"] == split and p["policy"] == policy and not p["censored"]]
            metrics[f"{split}/{policy}"] = {
                "model": errors([p["prediction"] for p in complete], [p["duration"] for p in complete]),
                "distance": errors([p["distance_prediction"] for p in complete], [p["duration"] for p in complete])}
    lines = ["# Real ML evaluation", "", f"Mode: {manifest['mode']}. Model: `{metadata['model_id']}`.",
             f"Selected: {metadata['selected_model']['kind']}; {metadata['training_samples']} training completions; "
             f"{metadata['training_censored']} censored training assignments.",
             f"Full pipeline wall time: {elapsed:.2f} seconds.", "",
             "| Split | Policy | Runs | Completed / released | Mean completion fraction | Mean completed latency | Fallbacks |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for split in ("test", "ood"):
        for policy in ("distance", "congestion", "learned"):
            group = [r for r in runs if r["split"] == split and r["policy"] == policy]
            latencies = [r["mean_latency"] for r in group if r["mean_latency"] is not None]
            latency_text = f"{mean(latencies):.2f}" if latencies else "N/A"
            lines.append(f"| {split} | {policy} | {len(group)} | "
                         f"{sum(r['completed'] for r in group)} / {sum(r['released'] for r in group)} | "
                         f"{mean(r['completion_fraction'] for r in group):.3f} | {latency_text} | "
                         f"{sum(r['model_fallbacks'] for r in group)} |")
    lines += ["", "Paired completion differences (learned minus baseline), by layout and demand:", "",
              "| Split | Layout | Demand | Baseline | Pairs | Mean delta ± sample SD |", "|---|---|---|---|---:|---:|"]
    keys = sorted({(p["split"], p["layout_id"], p["demand"], p["baseline"]) for p in paired})
    for split, layout, demand, baseline in keys:
        values = [p["delta_completed"] for p in paired if
                  (p["split"], p["layout_id"], p["demand"], p["baseline"]) == (split, layout, demand, baseline)]
        sd = f"{stdev(values):.2f}" if len(values) > 1 else "N/A"
        lines.append(f"| {split} | {layout[:10]} | {demand} | {baseline} | {len(values)} | {mean(values):.2f} ± {sd} |")
    lines += ["", "SD is descriptive, not a confidence interval. Completed latency excludes unfinished",
              "jobs and must be read with completion fractions and backlog. Waiting includes service.",
              "Collision violations: " + str(sum(r["vertex_violations"] + r["edge_violations"] for r in runs)) + ".", "",
              "## Limitations", "",
              "Models are small project implementations of ridge regression and a bootstrapped randomized",
              "regression forest, not scikit-learn. Package installation was blocked in the development",
              "session. Training, inference, and persistence use only standard Python and bounded JSON.",
              "Only completed assignments supply regression labels: censoring and collection-policy",
              "selection bias remain. Deployment changes the state distribution. Duration prediction",
              "is not counterfactual policy optimization; better MAE need not improve fleet throughput.",
              "Final results were not used to tune models. Any later tuning requires a fresh final split.",
              "Validation permutation importance is predictive, not causal. No physical validation."]
    return "\n".join(lines) + "\n", metrics


def pipeline(output, quick=False, install_demo=False):
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    (output / "evaluation").mkdir()
    start = perf_counter()
    manifest = split_manifest(quick)
    manifest.update(status="running", phase="collection", source_hashes={
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob("*.py"))})
    def checkpoint():
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    checkpoint()
    try:
        train_rows, train_summary = collect(manifest, "train", output / "train.json")
        val_rows, val_summary = collect(manifest, "validation", output / "validation.json")
        manifest.update(phase="fitting"); checkpoint()
        model, metadata = train_models(train_rows, val_rows, output)
        metadata.update(target="assignment-to-delivery completion in logical ticks",
                        split_groups=manifest["groups"],
                        training_data_sha256=hashlib.sha256((output / "train.json").read_bytes()).hexdigest(),
                        validation_data_sha256=hashlib.sha256((output / "validation.json").read_bytes()).hexdigest())
        manifest.update(phase="frozen-evaluation", frozen_model_id=metadata["model_id"]); checkpoint()
        # Test and OOD rollouts are generated only after hyperparameter selection.
        runs, predictions, paired = evaluate(manifest, model, metadata, output)
        write_csv(output / "feature-shift.csv", distribution_shift(train_rows, predictions))
        write_csv(output / "collection-summary.csv", train_summary + val_summary)
        text, metric = result_report(manifest, metadata, train_summary + val_summary,
                                     runs, predictions, paired, perf_counter() - start)
        (output / "report.md").write_text(text)
        (output / "prediction-metrics.json").write_text(json.dumps(metric, indent=2) + "\n")
        from .plots import generate_plots
        generate_plots(output, runs, predictions, paired)
        metadata.update(status="evaluated", mode=manifest["mode"],
                        evaluation_summary={key: value for key, value in metric.items()},
                        evaluation_report=str(output / "report.md"))
        save_model(model, output / "model", metadata)
        if install_demo:
            save_model(model, DEFAULT_MODEL, metadata)
        manifest.update(status="complete", phase="complete", elapsed_seconds=perf_counter() - start,
                        collection_runs=len(train_summary) + len(val_summary),
                        evaluation_runs=len(runs), scenario_cases=len({r["case"] for r in runs}))
        checkpoint()
        return manifest
    except KeyboardInterrupt:
        manifest.update(status="cancelled"); checkpoint()
        raise
    except Exception:
        manifest.update(status="failed"); checkpoint()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("runs/ml"))
    parser.add_argument("--install-demo", action="store_true")
    args = parser.parse_args()
    result = pipeline(args.output, args.quick, args.install_demo)
    print(json.dumps({key: result[key] for key in ("status", "elapsed_seconds", "collection_runs",
                                                  "evaluation_runs", "scenario_cases", "frozen_model_id")}, indent=2))


if __name__ == "__main__":
    main()
