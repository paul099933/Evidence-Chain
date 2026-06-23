#!/bin/bash
# generate.sh — JUnit XML → 结构化证据 JSON
# 用法: generate.sh <task_id> <junit_xml_path>
# 输出: 证据 JSON 到 stdout

set -euo pipefail

TASK_ID="${1}"
JUNIT_PATH="${2}"

python3 -c "
import json, hashlib, xml.etree.ElementTree as ET
from datetime import datetime

with open('${JUNIT_PATH}', 'rb') as f:
    content = f.read()
    hash_val = hashlib.sha256(content).hexdigest()

root = ET.fromstring(content)

passed = 0
failed = 0
errors = 0

# 处理 testsuites 包裹的情况
for suite in root.findall('.//testsuite'):
    t = int(suite.get('tests', 0))
    f = int(suite.get('failures', 0))
    e = int(suite.get('errors', 0))
    passed += (t - f - e)
    failed += f
    errors += e

# 如果顶层就是 testsuite
if root.tag == 'testsuite':
    t = int(root.get('tests', 0))
    f = int(root.get('failures', 0))
    e = int(root.get('errors', 0))
    passed = t - f - e
    failed = f
    errors = e

result = {
    'task_id': '${TASK_ID}',
    'hash': f'sha256:{hash_val}',
    'passed': passed,
    'failed': failed,
    'errors': errors,
    'timestamp': datetime.now().isoformat(),
    'junit_path': '${JUNIT_PATH}'
}

print(json.dumps(result, indent=2))
"
