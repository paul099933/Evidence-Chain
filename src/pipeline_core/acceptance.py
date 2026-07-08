from __future__ import annotations


def evaluate_acceptance(
    evidence: dict,
    acceptance_criteria: list[dict],
) -> tuple[str, list[str]]:
    """Evaluate acceptance criteria against evidence.

    Returns:
        ("pass", []) if all criteria pass.
        ("fail", [failed_gate_ids...]) otherwise.
    """
    failed_gates: list[str] = []

    for c in acceptance_criteria:
        check_type = c.get("check", "test_pass")
        if check_type != "test_pass":
            failed_gates.append(f"{c['id']}: unsupported check type {check_type}")
            continue

        tid = c.get("test_id") or c.get("id")
        if not tid:
            continue

        tests = evidence.get("tests", [])
        test = next(
            (t for t in tests if t.get("id") == tid or t.get("name") == tid),
            None,
        )
        if test is None or test.get("status") != "pass":
            failed_gates.append(c["id"])

    return ("pass", []) if not failed_gates else ("fail", failed_gates)
