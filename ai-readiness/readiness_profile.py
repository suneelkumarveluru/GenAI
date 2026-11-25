"""Aggregate fixed-bin profiles and compare batches without storing raw records."""
from bisect import bisect_right
import math


class Profile:
    def __init__(self, contract):
        self.edges = contract.get("histograms", {})
        self.categories = contract.get("allowed_values", {})
        self.numeric = {col: [0] * (len(edges) + 3) for col, edges in self.edges.items()}
        self.categorical = {col: [0] * (len(values) + 2) for col, values in self.categories.items()}
        self.category_indices = {
            col: {value: index for index, value in enumerate(values)}
            for col, values in self.categories.items()
        }

    def observe(self, row):
        for col, edges in self.edges.items():
            raw = (row.get(col) or "").strip()
            if not raw:
                index = len(edges) + 1  # blank
            else:
                try:
                    value = float(raw)
                    if not math.isfinite(value):
                        raise ValueError()
                    index = bisect_right(edges, value)
                except ValueError:
                    index = len(edges) + 2  # invalid
            self.numeric[col][index] += 1
        for col, values in self.categories.items():
            raw = (row.get(col) or "").strip()
            index = self.category_indices[col].get(raw, len(values) if raw else len(values) + 1)
            self.categorical[col][index] += 1

    def result(self):
        return {"numeric": self.numeric, "categorical": self.categorical}


def distance(left, right):
    """Total variation distance between two fixed-bin probability distributions."""
    n, m = sum(left), sum(right)
    if not n or not m:
        return 0.0 if n == m else 1.0
    if len(left) != len(right):
        raise ValueError("Incompatible profile shapes")
    return min(1.0, sum(abs(a / n - b / m) for a, b in zip(left, right)) / 2)


def compare(current, previous, policy):
    previous_rows = previous["rows"]
    row_change = (abs(current["rows"] - previous_rows) / previous_rows
                  if previous_rows else (0.0 if not current["rows"] else None))
    metrics = {"row_change": row_change, "distribution_distance": {}}
    violations = {}
    if "max_row_change" in policy and (row_change is None or row_change > policy["max_row_change"]):
        violations["drift:row_count"] = 1
    for group in ("numeric", "categorical"):
        for col, counts in current["profile"][group].items():
            score = distance(counts, previous["profile"][group][col])
            label = f"{group}:{col}"
            metrics["distribution_distance"][label] = score
            if score > policy.get("max_distribution_distance", 1):
                violations[f"drift:{label}"] = 1
    return metrics, violations
