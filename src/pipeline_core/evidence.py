from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from .schema import validate_evidence


def _parse_testsuite(suite: ET.Element) -> list[dict]:
    tests = []
    for tc in suite.findall("testcase"):
        fail = tc.find("failure")
        err = tc.find("error")
        skip = tc.find("skipped")
        status = "pass"
        message = ""
        if fail is not None:
            status = "fail"
            message = fail.get("message", "")
        elif err is not None:
            status = "error"
            message = err.get("message", "")
        elif skip is not None:
            status = "skip"
            message = skip.get("message", "")
        tests.append(
            {
                "id": tc.get("name", "unknown"),
                "name": tc.get("name", "unknown"),
                "classname": tc.get("classname", ""),
                "status": status,
                "message": message,
            }
        )
    return tests


def parse_junit(
    xml_content: str,
    *,
    task_id: str,
    nonce: str,
    junit_path: str,
) -> dict:
    """Parse JUnit XML into canonical evidence dict."""
    root = ET.fromstring(xml_content)

    passed, failed, errors, skipped = 0, 0, 0, 0
    tests: list[dict] = []

    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")

    for suite in suites:
        t = int(suite.get("tests", 0))
        f = int(suite.get("failures", 0))
        e = int(suite.get("errors", 0))
        s = int(suite.get("skipped", 0))
        passed += t - f - e - s
        failed += f
        errors += e
        skipped += s
        tests.extend(_parse_testsuite(suite))

    sha = hashlib.sha256(xml_content.encode("utf-8")).hexdigest()

    return {
        "task_id": task_id,
        "nonce": nonce,
        "sha256": sha,
        "junit_path": junit_path,
        "timestamp": datetime.now().isoformat(),
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "tests": tests,
    }


def write_evidence(evidence: dict, evidence_dir: str) -> str:
    """Write evidence dict to evidence.json. Returns the file path."""
    os.makedirs(evidence_dir, exist_ok=True)
    path = os.path.join(evidence_dir, "evidence.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(evidence, f, ensure_ascii=False, indent=2)
    return path


def load_evidence(evidence_dir: str) -> dict:
    """Load evidence.json from directory."""
    path = os.path.join(evidence_dir, "evidence.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_and_validate(evidence_dir: str) -> tuple[dict, list[str]]:
    """Load evidence and validate schema."""
    ev = load_evidence(evidence_dir)
    return ev, validate_evidence(ev)


def evidence_from_junit_file(
    *,
    task_id: str,
    nonce: str,
    junit_path: str,
    evidence_dir: str,
) -> str:
    """Convenience: read JUnit XML file, parse, validate, write evidence.json."""
    path = Path(junit_path)
    xml_content = path.read_text(encoding="utf-8")
    ev = parse_junit(
        xml_content,
        task_id=task_id,
        nonce=nonce,
        junit_path=junit_path,
    )
    validation_errors = validate_evidence(ev)
    if validation_errors:
        raise ValueError(f"generated evidence invalid: {validation_errors}")
    return write_evidence(ev, evidence_dir)
