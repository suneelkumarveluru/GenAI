"""Validate and fingerprint versioned data contracts before scanning a file."""
import hashlib
import json
import math


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _columns(value):
    return (
        isinstance(value, list)
        and all(isinstance(x, str) and x.strip() for x in value)
        and len(set(value)) == len(value)
    )


def validate_contract(contract):
    """Reject invalid and unknown settings rather than silently skipping rules."""
    _require(isinstance(contract, dict), "Contract must be an object")
    supported = {
        "dataset", "version", "required", "unique", "composite_keys",
        "numeric", "allowed_values", "freshness", "min_rows", "max_rows",
        "max_null_fraction", "schema", "allow_extra_columns", "histograms",
        "drift",
    }
    _require(not (set(contract) - supported), "Unknown contract setting")
    for field in ("dataset", "version"):
        v = contract.get(field, "default" if field == "dataset" else "1")
        _require(isinstance(v, str) and v.strip(), f"{field} must be nonempty text")
    for field in ("required", "unique", "schema"):
        _require(_columns(contract.get(field, [])), f"Invalid {field} columns")
    keys = contract.get("composite_keys", [])
    _require(isinstance(keys, list) and all(_columns(key) and len(key) >= 2 for key in keys),
             "Composite keys require at least two distinct columns")
    _require(len({tuple(key) for key in keys}) == len(keys), "Repeated composite key")
    for name in ("numeric", "allowed_values", "max_null_fraction", "histograms"):
        rules = contract.get(name, {})
        _require(isinstance(rules, dict) and all(isinstance(k, str) and k.strip() for k in rules),
                 f"Invalid {name} mapping")
    for limits in contract.get("numeric", {}).values():
        _require(isinstance(limits, dict) and not (set(limits) - {"min", "max"})
                 and all(_number(x) for x in limits.values()), "Invalid numeric limits")
        _require(limits.get("min", -math.inf) <= limits.get("max", math.inf),
                 "Numeric minimum exceeds maximum")
    for values in contract.get("allowed_values", {}).values():
        _require(_columns(values) and bool(values) and all(x == x.strip() for x in values),
                 "Allowed values must be distinct nonblank strings without surrounding whitespace")
    for fraction in contract.get("max_null_fraction", {}).values():
        _require(_number(fraction) and 0 <= fraction <= 1, "Null fraction outside [0,1]")
    for edges in contract.get("histograms", {}).values():
        _require(isinstance(edges, list) and bool(edges) and all(_number(x) for x in edges)
                 and all(a < b for a, b in zip(edges, edges[1:])), "Histogram edges must increase")
    if "freshness" in contract:
        fresh = contract["freshness"]
        _require(isinstance(fresh, dict) and set(fresh) == {"column", "max_age_hours"}
                 and isinstance(fresh["column"], str) and fresh["column"].strip()
                 and _number(fresh["max_age_hours"]) and fresh["max_age_hours"] >= 0,
                 "Invalid freshness policy")
    for field in ("min_rows", "max_rows"):
        if field in contract:
            _require(type(contract[field]) is int and contract[field] >= 0, f"Bad {field}")
    _require(contract.get("min_rows", 1) <= contract.get("max_rows", math.inf),
             "Row minimum exceeds maximum")
    _require(type(contract.get("allow_extra_columns", True)) is bool,
             "allow_extra_columns must be Boolean")
    if not contract.get("allow_extra_columns", True):
        _require(bool(contract.get("schema")), "Strict schema requires declared columns")
    if "schema" in contract:
        _require(expected_columns(contract) <= set(contract["schema"]),
                 "Rules reference columns outside the declared schema")
    drift = contract.get("drift", {})
    _require(isinstance(drift, dict) and not (set(drift) - {"max_row_change", "max_distribution_distance"}),
             "Unknown drift setting")
    for value in drift.values():
        _require(_number(value) and value >= 0, "Drift thresholds must be nonnegative")
    _require(drift.get("max_distribution_distance", 1) <= 1,
             "Distribution distance threshold exceeds 1")
    if "max_distribution_distance" in drift:
        _require(bool(contract.get("histograms") or contract.get("allowed_values")),
                 "Distribution drift needs histogram or categorical profiles")
    return contract


def expected_columns(contract):
    columns = set(contract.get("schema", []))
    for field in ("required", "unique", "numeric", "allowed_values", "max_null_fraction", "histograms"):
        columns.update(contract.get(field, []))
    for key in contract.get("composite_keys", []):
        columns.update(key)
    if contract.get("freshness"):
        columns.add(contract["freshness"]["column"])
    return columns


def fingerprint(contract):
    payload = json.dumps(contract, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
