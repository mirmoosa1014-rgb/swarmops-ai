"""Small supervised regressors with bounded JSON persistence; no pickle/code loading.

These are project implementations, not scikit-learn estimators. Both learn the
residual beyond the static travel/service estimate from completed assignments.
"""
from dataclasses import asdict
import hashlib
import json
from math import isfinite, sqrt
from pathlib import Path
import random
from statistics import mean
from time import perf_counter

FEATURES = ("empty_distance", "loaded_distance", "service_ticks", "occupied_route_cells",
            "nearby_robots", "queue_length", "fleet_size", "available_robots",
            "active_jobs", "free_cells", "narrow_fraction")
DEFAULT_MODEL = Path(__file__).resolve().parents[2] / "models" / "demo"


def features(candidate):
    return [float(getattr(candidate, key)) for key in FEATURES]


def base_duration(row):
    return max(1, row[0]) + max(1, row[1]) + 2 * row[2]


def solve(matrix, target):
    """Partial-pivot Gaussian elimination for the tiny regularized normal system."""
    rows = [list(row) + [value] for row, value in zip(matrix, target)]
    n = len(rows)
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(rows[r][col]))
        rows[col], rows[pivot] = rows[pivot], rows[col]
        if abs(rows[col][col]) < 1e-12:
            raise ValueError("Singular regression system")
        scale = rows[col][col]
        rows[col] = [v / scale for v in rows[col]]
        for r in range(n):
            if r == col:
                continue
            scale = rows[r][col]
            rows[r] = [a - scale * b for a, b in zip(rows[r], rows[col])]
    return [row[-1] for row in rows]


class DurationModel:
    def __init__(self, kind="forest", *, trees=24, depth=5, leaf=8, seed=17):
        if kind not in ("linear", "forest") or not 1 <= trees <= 64 or not 1 <= depth <= 8 or leaf < 2:
            raise ValueError("Unsupported model configuration")
        self.kind, self.trees, self.depth, self.leaf, self.seed = kind, trees, depth, leaf, seed
        self.state = {}

    def fit(self, x, y):
        if len(x) < 12 or len(x) != len(y):
            raise ValueError("Need at least 12 aligned training samples")
        if any(len(row) != len(FEATURES) or not all(isfinite(v) for v in row) for row in x):
            raise ValueError("Invalid training features")
        if any(not isfinite(v) or v <= 0 for v in y):
            raise ValueError("Invalid training targets")
        residual = [target - base_duration(row) for row, target in zip(x, y)]
        if self.kind == "linear":
            centers = [mean(row[j] for row in x) for j in range(len(FEATURES))]
            scales = [max(1e-6, sqrt(mean((row[j] - centers[j]) ** 2 for row in x)))
                      for j in range(len(FEATURES))]
            z = [[1.0] + [(v - c) / s for v, c, s in zip(row, centers, scales)] for row in x]
            n = len(FEATURES) + 1
            matrix = [[sum(row[i] * row[j] for row in z) + (1.0 if i == j and i > 0 else 0)
                       for j in range(n)] for i in range(n)]
            weights = solve(matrix, [sum(row[i] * t for row, t in zip(z, residual)) for i in range(n)])
            self.state = {"centers": centers, "scales": scales, "weights": weights}
        else:
            rng = random.Random(self.seed)
            def build(indices, depth):
                values = [residual[i] for i in indices]
                average = mean(values)
                if depth == 0 or len(indices) < self.leaf * 2:
                    return {"value": average}
                best = None
                for feature in rng.sample(range(len(FEATURES)), 4):
                    ordered = sorted(set(x[i][feature] for i in indices))
                    if len(ordered) < 2:
                        continue
                    positions = sorted({min(len(ordered) - 2, k * (len(ordered) - 1) // 8) for k in range(1, 8)})
                    for pos in positions:
                        threshold = (ordered[pos] + ordered[pos + 1]) / 2
                        left = [i for i in indices if x[i][feature] <= threshold]
                        right = [i for i in indices if x[i][feature] > threshold]
                        if min(len(left), len(right)) < self.leaf:
                            continue
                        def sse(part):
                            total = sum(residual[i] for i in part)
                            return sum(residual[i] ** 2 for i in part) - total * total / len(part)
                        loss = sse(left) + sse(right)
                        if best is None or loss < best[0]:
                            best = (loss, feature, threshold, left, right)
                if best is None:
                    return {"value": average}
                _, feature, threshold, left, right = best
                return {"feature": feature, "threshold": threshold,
                        "left": build(left, depth - 1), "right": build(right, depth - 1)}
            self.state = {"forest": [build([rng.randrange(len(x)) for _ in x], self.depth)
                                     for _ in range(self.trees)]}
        return self

    def predict(self, rows):
        if not self.state:
            raise ValueError("Model has not been fitted")
        output = []
        for row in rows:
            if len(row) != len(FEATURES) or not all(isfinite(v) for v in row):
                raise ValueError("Invalid inference feature schema")
            if self.kind == "linear":
                z = [1.0] + [(v - c) / s for v, c, s in zip(row, self.state["centers"], self.state["scales"])]
                residual = sum(a * b for a, b in zip(z, self.state["weights"]))
            else:
                values = []
                for tree in self.state["forest"]:
                    while "value" not in tree:
                        tree = tree["left"] if row[tree["feature"]] <= tree["threshold"] else tree["right"]
                    values.append(tree["value"])
                residual = mean(values)
            output.append(base_duration(row) + residual)
        return output

    def to_dict(self):
        return {"format_version": 1, "features": list(FEATURES), "kind": self.kind,
                "config": {"trees": self.trees, "depth": self.depth, "leaf": self.leaf, "seed": self.seed},
                "state": self.state}

    @classmethod
    def from_dict(cls, data):
        if data.get("format_version") != 1 or data.get("features") != list(FEATURES):
            raise ValueError("Unsupported model format or feature order")
        model = cls(data["kind"], **data["config"])
        state = data["state"]
        def finite_list(values, n):
            if len(values) != n or not all(type(v) in (int, float) and isfinite(v) for v in values):
                raise ValueError("Invalid model numbers")
        if model.kind == "linear":
            for key, n in (("centers", 11), ("scales", 11), ("weights", 12)):
                finite_list(state[key], n)
            if min(state["scales"]) <= 0:
                raise ValueError("Invalid scaling")
        else:
            if not 1 <= len(state["forest"]) <= 64:
                raise ValueError("Invalid forest size")
            def check(node, depth=0):
                if depth > 8:
                    raise ValueError("Model tree too deep")
                if "value" in node:
                    finite_list([node["value"]], 1)
                else:
                    if type(node["feature"]) is not int or not 0 <= node["feature"] < len(FEATURES):
                        raise ValueError("Invalid feature index")
                    finite_list([node["threshold"]], 1)
                    check(node["left"], depth + 1); check(node["right"], depth + 1)
            for tree in state["forest"]:
                check(tree)
        model.state = state
        return model


def save_model(model, directory, metadata):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    content = json.dumps(model.to_dict(), sort_keys=True, allow_nan=False).encode()
    identity = hashlib.sha256(content).hexdigest()
    (directory / "model.json").write_bytes(content)
    (directory / "metadata.json").write_text(json.dumps({**metadata, "model_id": identity,
                                                        "features": list(FEATURES)}, indent=2) + "\n")
    return identity


def load_model(directory=DEFAULT_MODEL):
    directory = Path(directory)
    content = (directory / "model.json").read_bytes()
    if len(content) > 2_000_000:
        raise ValueError("Model exceeds 2 MB")
    metadata = json.loads((directory / "metadata.json").read_text())
    if hashlib.sha256(content).hexdigest() != metadata["model_id"]:
        raise ValueError("Model integrity mismatch")
    return DurationModel.from_dict(json.loads(content)), metadata


class LearnedPolicy:
    name = "learned"

    def __init__(self, model=None, metadata=None):
        self.model, self.metadata = load_model() if model is None else (model, metadata or {})
        self.fallbacks = 0
        self.prediction_count = 0
        self.predict_seconds = 0.0

    def score_many(self, candidates):
        if not candidates:
            return []
        x = [features(c) for c in candidates]
        start = perf_counter()
        self.prediction_count += len(x)
        try:
            predicted = self.model.predict(x)
            if len(predicted) != len(x):
                raise ValueError("Prediction count mismatch")
        except (ValueError, ArithmeticError, OverflowError):
            predicted = [float("nan")] * len(x)
        self.predict_seconds += perf_counter() - start
        scores = []
        for candidate, row, value in zip(candidates, x, predicted):
            unsupported = (not all(isfinite(v) and v >= 0 for v in row) or candidate.fleet_size > 8
                           or candidate.empty_distance + candidate.loaded_distance > 200)
            if unsupported or not isfinite(value) or not 0 < value <= 25000:
                self.fallbacks += 1
                value = candidate.distance_estimate
            scores.append(float(value))
        return scores

    def score(self, candidate):
        return self.score_many((candidate,))[0]
