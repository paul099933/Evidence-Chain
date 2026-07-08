import hashlib
import os

from pipeline_core.evidence import (
    evidence_from_junit_file,
    load_and_validate,
    parse_junit,
    write_evidence,
)


def test_parse_junit_toplevel_testsuite():
    xml = """<?xml version="1.0"?>
    <testsuite tests="2" failures="1" errors="0" skipped="0">
      <testcase name="t1" classname="c1"/>
      <testcase name="t2" classname="c1">
        <failure message="boom"/>
      </testcase>
    </testsuite>
    """
    ev = parse_junit(
        xml,
        task_id="task-1",
        nonce="nonce-1",
        junit_path="/tmp/report.xml",
    )
    assert ev["passed"] == 1
    assert ev["failed"] == 1
    assert ev["errors"] == 0
    assert ev["sha256"] == hashlib.sha256(xml.encode("utf-8")).hexdigest()
    assert ev["tests"][1]["status"] == "fail"
    assert ev["tests"][1]["message"] == "boom"


def test_parse_junit_testsuites_wrapper():
    xml = """<?xml version="1.0"?>
    <testsuites>
      <testsuite tests="1" failures="0" errors="0" skipped="0">
        <testcase name="t1" classname="c1"/>
      </testsuite>
      <testsuite tests="1" failures="1" errors="0" skipped="0">
        <testcase name="t2" classname="c2">
          <failure message="oops"/>
        </testcase>
      </testsuite>
    </testsuites>
    """
    ev = parse_junit(xml, task_id="task-2", nonce="nonce-2", junit_path="/tmp/report.xml")
    assert ev["passed"] == 1
    assert ev["failed"] == 1
    assert len(ev["tests"]) == 2


def test_parse_junit_error_and_skip():
    xml = """<?xml version="1.0"?>
    <testsuite tests="2" failures="0" errors="1" skipped="1">
      <testcase name="t1"><error message="err"/></testcase>
      <testcase name="t2"><skipped message="skip"/></testcase>
    </testsuite>
    """
    ev = parse_junit(xml, task_id="task-3", nonce="nonce-3", junit_path="/tmp/report.xml")
    assert ev["errors"] == 1
    assert ev["skipped"] == 1
    assert ev["tests"][0]["status"] == "error"
    assert ev["tests"][1]["status"] == "skip"


def test_write_and_load_evidence(temp_dir):
    ev = {
        "task_id": "task-4",
        "nonce": "nonce-4",
        "sha256": "abc",
        "junit_path": "/tmp/report.xml",
        "timestamp": "2026-06-30T00:00:00",
        "passed": 1,
        "failed": 0,
        "errors": 0,
        "tests": [{"id": "t1", "name": "t1", "status": "pass"}],
    }
    path = write_evidence(ev, temp_dir)
    assert os.path.basename(path) == "evidence.json"
    loaded, errors = load_and_validate(temp_dir)
    assert errors == []
    assert loaded["task_id"] == "task-4"


def test_evidence_from_junit_file(temp_dir):
    xml = """<?xml version="1.0"?>
    <testsuite tests="1" failures="0" errors="0" skipped="0">
      <testcase name="hello" classname="suite"/>
    </testsuite>
    """
    junit_path = os.path.join(temp_dir, "report.xml")
    with open(junit_path, "w", encoding="utf-8") as f:
        f.write(xml)

    evidence_dir = os.path.join(temp_dir, "evidence")
    out_path = evidence_from_junit_file(
        task_id="task-5",
        nonce="nonce-5",
        junit_path=junit_path,
        evidence_dir=evidence_dir,
    )
    assert os.path.basename(out_path) == "evidence.json"
    loaded, errors = load_and_validate(evidence_dir)
    assert errors == []
    assert loaded["passed"] == 1
    assert loaded["tests"][0]["id"] == "hello"
    assert loaded["nonce"] == "nonce-5"
