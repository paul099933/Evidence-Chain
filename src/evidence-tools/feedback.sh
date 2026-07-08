#!/bin/bash
# feedback.sh — 测试失败时创建 Fixer 子任务
# 用法: feedback.sh <runner_task_id> <evidence_json_file>

set -euo pipefail

RUNNER_TASK_ID="${1}"
EVIDENCE_FILE="${2}"

if [ ! -f "${EVIDENCE_FILE}" ]; then
    echo "Evidence file not found: ${EVIDENCE_FILE}" >&2
    exit 1
fi

HASH=$(jq -r '.sha256' "${EVIDENCE_FILE}")
FAILED=$(jq -r '.failed' "${EVIDENCE_FILE}")
PASSED=$(jq -r '.passed' "${EVIDENCE_FILE}")
JUNIT_PATH=$(jq -r '.junit_path' "${EVIDENCE_FILE}")

# 从 JUnit XML 提取失败详情
FAILURES=$(python3 -c "
import xml.etree.ElementTree as ET
root = ET.parse('${JUNIT_PATH}').getroot()
cases = root.findall('.//testcase')
for c in cases:
    failure = c.find('failure')
    if failure is not None:
        msg = failure.get('message', '')
        print(f'FAILED {c.get(\"classname\", \"\")}::{c.get(\"name\", \"\")} - {msg}')
" | head -n 20)

# 创建 Fixer 任务
kanban_create \
    --title "Fix: ${RUNNER_TASK_ID}" \
    --assignee fixer \
    --parents "${RUNNER_TASK_ID}" \
    --body "Task: Fix test failures from ${RUNNER_TASK_ID}

Evidence:
Hash: ${HASH}
Passed: ${PASSED}
Failed: ${FAILED}

Failure Details:
${FAILURES}

Scope:
{\"retry_count\":0,\"max_retries\":3}
"

echo "Fixer task created for ${RUNNER_TASK_ID}"
