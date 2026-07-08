from __future__ import annotations

EVIDENCE_REQUIRED_FIELDS = {
    "task_id",
    "nonce",
    "sha256",
    "junit_path",
    "timestamp",
    "passed",
    "failed",
    "errors",
    "tests",
}

VALID_STATUSES = {"pass", "fail", "error", "skip"}


def validate_evidence(ev: dict) -> list[str]:
    """Validate an evidence dict against the canonical schema.

    Returns a list of human-readable error messages. Empty list means valid.
    """
    errors: list[str] = []

    if not isinstance(ev, dict):
        errors.append("evidence must be an object")
        return errors

    missing = sorted(EVIDENCE_REQUIRED_FIELDS - set(ev.keys()))
    if missing:
        errors.append(f"missing fields: {missing}")
        return errors

    for field in ("passed", "failed", "errors"):
        if not isinstance(ev[field], int):
            errors.append(f"{field} must be int, got {type(ev[field]).__name__}")

    if not isinstance(ev["tests"], list):
        errors.append("tests must be a list")
        return errors

    for idx, t in enumerate(ev["tests"]):
        if not isinstance(t, dict):
            errors.append(f"tests[{idx}] must be an object")
            continue
        for field in ("id", "name", "status"):
            if field not in t:
                errors.append(f"tests[{idx}] missing {field}")
        status = t.get("status")
        if status not in VALID_STATUSES:
            errors.append(f"tests[{idx}] invalid status: {status!r}")

    return errors
