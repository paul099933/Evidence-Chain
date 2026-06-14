#!/bin/bash
# run-test.sh — 统一测试入口（绝对路径版）
set -uo pipefail

TASK_ID="${1:-default}"
TEST_SELECTOR="${2:-}"
PROJECT_DIR="${3:-$(pwd)}"

# 获取真实 home 目录（不受 $HOME 覆盖影响）
REAL_HOME="$(getent passwd "$(whoami 2>/dev/null || echo "${USER:-agent}")" 2>/dev/null | cut -d: -f6)"
REAL_HOME="${REAL_HOME:-/home/agent}"
EVIDENCE_TOOLS="${REAL_HOME}/.hermes/evidence-tools"

EVIDENCE_DIR="${REAL_HOME}/.hermes/evidence-archive/${TASK_ID}"
mkdir -p "${EVIDENCE_DIR}"
JUNIT_PATH="${EVIDENCE_DIR}/report.xml"

cd "${PROJECT_DIR}"

# 强制还原未提交的源码修改——Runner 只测不改
if ! git diff --quiet; then
    echo "[RUNNER_BLOCK] detected uncommitted source changes, reverting"
    git checkout -- '*.py' '*.js' '*.ts' '*.go' '*.rs' '*.sh' 2>/dev/null || true
fi

if [ -f "pytest.ini" ] || [ -f "pyproject.toml" ]; then
    pytest "${TEST_SELECTOR}" --junitxml="${JUNIT_PATH}" --tb=short
elif [ -f "package.json" ]; then
    npm test -- "${TEST_SELECTOR}" --reporter=junit --outputFile="${JUNIT_PATH}"
elif [ -f "go.mod" ]; then
    go test ./... -json > "${EVIDENCE_DIR}/raw.json"
elif [ -f "${PROJECT_DIR}/.evidence/test-manifest.yaml" ]; then
    echo "[run-test] Detected .evidence/test-manifest.yaml"
    JUNIT_PATH="${JUNIT_PATH}" \
    EVIDENCE_TOOLS="${EVIDENCE_TOOLS}" \
    PROJECT_DIR="${PROJECT_DIR}" \
    bash -c "$(python3 -c "
import yaml
with open('${PROJECT_DIR}/.evidence/test-manifest.yaml') as f:
    d = yaml.safe_load(f)
print(d.get('test_command', ''))
")" "${JUNIT_PATH}"
elif [ -x "${EVIDENCE_TOOLS}/test-sfp.sh" ]; then
    echo "[run-test] Detected SFP integration test"
    SFP_DIR="${PROJECT_DIR}" bash "${EVIDENCE_TOOLS}/test-sfp.sh" "${JUNIT_PATH}"
else
    bash "${TEST_SELECTOR}" "${JUNIT_PATH}"
fi

"${EVIDENCE_TOOLS}/generate.sh" "${TASK_ID}" "${JUNIT_PATH}"

echo "[INFO] 完成"
