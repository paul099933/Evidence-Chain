import pytest

from pipeline_core.schema import validate_evidence


def sample_evidence(**overrides):
    base = {
        "task_id": "task-1",
        "nonce": "abc123",
        "sha256": "deadbeef",
        "junit_path": "/tmp/report.xml",
        "timestamp": "2026-06-30T00:00:00",
        "passed": 1,
        "failed": 0,
        "errors": 0,
        "tests": [
            {"id": "t1", "name": "t1", "status": "pass"},
        ],
    }
    base.update(overrides)
    return base


def test_valid_evidence():
    assert validate_evidence(sample_evidence()) == []


def test_missing_fields():
    ev = sample_evidence()
    del ev["sha256"]
    del ev["tests"]
    errors = validate_evidence(ev)
    assert any("missing fields" in e for e in errors)
    assert "sha256" in "".join(errors)


def test_non_object_evidence():
    assert validate_evidence("not a dict") == ["evidence must be an object"]


def test_tests_not_list():
    errors = validate_evidence(sample_evidence(tests="bad"))
    assert any("tests must be a list" in e for e in errors)


def test_test_missing_fields():
    errors = validate_evidence(sample_evidence(tests=[{"id": "t1"}]))
    assert any("tests[0] missing name" in e for e in errors)
    assert any("tests[0] missing status" in e for e in errors)


def test_invalid_status():
    errors = validate_evidence(
        sample_evidence(tests=[{"id": "t1", "name": "t1", "status": "unknown"}])
    )
    assert any("invalid status" in e for e in errors)


def test_counters_must_be_int():
    errors = validate_evidence(sample_evidence(passed="1"))
    assert any("passed must be int" in e for e in errors)
