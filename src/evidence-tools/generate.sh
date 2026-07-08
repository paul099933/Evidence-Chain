#!/bin/bash
# generate.sh — JUnit XML → 结构化证据 JSON
# 用法: generate.sh <task_id> <junit_xml_path> <evidence_dir>
# 输出: ${evidence_dir}/evidence.json
set -euo pipefail

TASK_ID="${1}"
JUNIT_PATH="${2}"
EVIDENCE_DIR="${3}"
NONCE="${NONCE:-}"

mkdir -p "${EVIDENCE_DIR}"

python3 -c "
import json, hashlib, xml.etree.ElementTree as ET, os
from datetime import datetime

task_id = '${TASK_ID}'
junit_path = '${JUNIT_PATH}'
nonce = '${NONCE}'

with open(junit_path, 'rb') as f:
    raw = f.read()
sha = hashlib.sha256(raw).hexdigest()
root = ET.fromstring(raw)

passed, failed, errors, skipped = 0, 0, 0, 0
tests = []

suites = [root] if root.tag == 'testsuite' else root.findall('testsuite')

for suite in suites:
    t = int(suite.get('tests', 0))
    f = int(suite.get('failures', 0))
    e = int(suite.get('errors', 0))
    s = int(suite.get('skipped', 0))
    passed += t - f - e - s
    failed += f
    errors += e
    skipped += s

    for tc in suite.findall('testcase'):
        fail = tc.find('failure')
        err = tc.find('error')
        skip = tc.find('skipped')
        status = 'pass'
        msg = ''
        if fail is not None:
            status = 'fail'
            msg = fail.get('message', '')
        elif err is not None:
            status = 'error'
            msg = err.get('message', '')
        elif skip is not None:
            status = 'skip'
            msg = skip.get('message', '')
        tests.append({
            'id': tc.get('name', 'unknown'),
            'name': tc.get('name', 'unknown'),
            'classname': tc.get('classname', ''),
            'status': status,
            'message': msg,
        })

result = {
    'task_id': task_id,
    'nonce': nonce,
    'sha256': sha,
    'junit_path': junit_path,
    'timestamp': datetime.now().isoformat(),
    'passed': passed,
    'failed': failed,
    'errors': errors,
    'skipped': skipped,
    'tests': tests,
}

out_path = os.path.join('${EVIDENCE_DIR}', 'evidence.json')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f'[generate] wrote {out_path}')
"
