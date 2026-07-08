from pipeline_core.acceptance import evaluate_acceptance


def make_evidence(tests):
    return {
        "task_id": "t",
        "nonce": "n",
        "sha256": "s",
        "junit_path": "/tmp/r.xml",
        "timestamp": "2026-06-30T00:00:00",
        "passed": sum(1 for t in tests if t["status"] == "pass"),
        "failed": sum(1 for t in tests if t["status"] == "fail"),
        "errors": 0,
        "tests": tests,
    }


def test_all_pass():
    ev = make_evidence([{"id": "t1", "name": "t1", "status": "pass"}])
    criteria = [{"id": "AC1", "description": "t1 passes", "test_id": "t1"}]
    status, failed = evaluate_acceptance(ev, criteria)
    assert status == "pass"
    assert failed == []


def test_one_fails():
    ev = make_evidence(
        [
            {"id": "t1", "name": "t1", "status": "pass"},
            {"id": "t2", "name": "t2", "status": "fail"},
        ]
    )
    criteria = [
        {"id": "AC1", "description": "t1", "test_id": "t1"},
        {"id": "AC2", "description": "t2", "test_id": "t2"},
    ]
    status, failed = evaluate_acceptance(ev, criteria)
    assert status == "fail"
    assert failed == ["AC2"]


def test_test_id_not_found():
    ev = make_evidence([{"id": "t1", "name": "t1", "status": "pass"}])
    criteria = [{"id": "AC1", "description": "missing", "test_id": "t99"}]
    status, failed = evaluate_acceptance(ev, criteria)
    assert status == "fail"
    assert failed == ["AC1"]


def test_uses_id_when_test_id_missing():
    ev = make_evidence([{"id": "t1", "name": "t1", "status": "pass"}])
    criteria = [{"id": "t1", "description": "uses id"}]
    status, failed = evaluate_acceptance(ev, criteria)
    assert status == "pass"


def test_empty_criteria():
    ev = make_evidence([{"id": "t1", "name": "t1", "status": "fail"}])
    status, failed = evaluate_acceptance(ev, [])
    assert status == "pass"
    assert failed == []


def test_unsupported_check_type():
    ev = make_evidence([{"id": "t1", "name": "t1", "status": "pass"}])
    criteria = [{"id": "AC1", "description": "x", "check": "coverage_min"}]
    status, failed = evaluate_acceptance(ev, criteria)
    assert status == "fail"
    assert any("unsupported check type" in f for f in failed)
