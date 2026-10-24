"""Verify saved full ML evidence and replay one learned-policy case."""
import csv
import hashlib
import json
from pathlib import Path
from swarmops.datasets import assert_disjoint, make_scenario, rollout
from swarmops.experiments import scenario_hash
from swarmops.models import DEFAULT_MODEL, FEATURES, LearnedPolicy, load_model


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "results/ml-full"
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == "complete"
    assert_disjoint(manifest)
    for name, digest in manifest["source_hashes"].items():
        assert hashlib.sha256((root / "src/swarmops" / name).read_bytes()).hexdigest() == digest, name
    model, metadata = load_model(output / "model")
    bundled, bundled_meta = load_model(DEFAULT_MODEL)
    assert metadata["model_id"] == manifest["frozen_model_id"] == bundled_meta["model_id"]
    assert model.to_dict() == bundled.to_dict()
    for name in ("train", "validation"):
        raw = (output / f"{name}.json").read_bytes()
        key = "training" if name == "train" else "validation"
        assert hashlib.sha256(raw).hexdigest() == metadata[f"{key}_data_sha256"]
        for row in json.loads(raw)["samples"]:
            assert set(FEATURES) <= set(row)
            assert row["censored"] == (row["duration"] is None)
            assert row["duration"] is None or 0 < row["duration"] <= row["observed_lower_bound"]
    with (output / "evaluation-runs.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == manifest["evaluation_runs"]
    cases, replay, assignments = {}, None, 0
    for row in rows:
        split, index, seed, demand = row["case"].split("-")
        layout = manifest["groups"][split]["layouts"][int(index)]
        interval = manifest["ood_interval"] if split == "ood" else manifest["demands"][demand]
        scenario = make_scenario(layout, int(seed), interval, manifest["horizon"], 8 if split == "ood" else 4)
        assert scenario_hash(scenario) == row["scenario_hash"]
        assert int(row["vertex_violations"]) == int(row["edge_violations"]) == 0
        detail = json.loads((output / "evaluation" / f"{row['case']}-{row['policy']}.json").read_text())
        assert detail["summary"]["scenario_hash"] == row["scenario_hash"]
        for decision in detail["assignments"]:
            job = detail["jobs"][decision["job_id"]]
            assert job["assigned"] == decision["observed_tick"] >= job["spec"]["release"]
        assignments += len(detail["assignments"])
        cases.setdefault(row["case"], []).append(row)
        if row["policy"] == "learned" and replay is None:
            sim, dispatcher = rollout(scenario, LearnedPolicy(model, metadata))
            # JSON converts coordinate tuples to lists; compare at export boundary.
            assert json.loads(json.dumps(sim.events)) == detail["events"]
            assert dispatcher.decisions == detail["assignments"]
            replay = row["case"]
    for group in cases.values():
        assert {r["policy"] for r in group} == {"distance", "congestion", "learned"}
        assert len({(r["scenario_hash"], r["tick"], r["released"]) for r in group}) == 1
    result = {"passed": True, "run_records_checked": len(rows), "scenario_cases": len(cases),
              "assignment_records_checked": assignments, "model_id": metadata["model_id"],
              "replayed_case": replay, "source_hashes_match": True, "split_disjointness": True,
              "browser_ui_verified": False, "png_exported": False}
    (output / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
