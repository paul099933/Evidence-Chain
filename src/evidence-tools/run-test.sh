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

# === Pipeline 入口验证 ===
if [ -z "${HERMES_KANBAN_TASK}" ]; then
    echo "FATAL: HERMES_KANBAN_TASK not set. Must run via Pipeline Plugin." >&2
    exit 1
fi

BODY=$(hermes kanban show "${HERMES_KANBAN_TASK}" --json 2>/dev/null)
if [ -z "$BODY" ]; then
    echo "FATAL: Task ${HERMES_KANBAN_TASK} not found in Kanban DB." >&2
    exit 1
fi

NONCE=$(echo "$BODY" | python3 -c 'import sys,json; print(json.load(sys.stdin)["task"]["body"])' 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin).get("Nonce",""))' 2>/dev/null)

if [ -z "$NONCE" ]; then
    echo "FATAL: No Plugin nonce. Must run via pipeline_start." >&2
    exit 1
fi

export NONCE="$NONCE"
# === 验证结束 ===

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

    # 读取 manifest，提取 tests[].script 列表
    SCRIPT_LIST=$(python3 -c "
import yaml, json
with open('${PROJECT_DIR}/.evidence/test-manifest.yaml') as f:
    d = yaml.safe_load(f)
tests = d.get('tests') or []
scripts = [t['script'] for t in tests if t.get('script')]
print(json.dumps(scripts))
")

    if [ -z "${SCRIPT_LIST}" ] || [ "x${SCRIPT_LIST}" = "x[]" ]; then
        # 兼容旧格式：只有 test_command 字段
        echo "[run-test] No tests[].script found, falling back to test_command"
        JUNIT_PATH="${JUNIT_PATH}" \
        EVIDENCE_TOOLS="${EVIDENCE_TOOLS}" \
        PROJECT_DIR="${PROJECT_DIR}" \
        bash -c "$(python3 -c "
import yaml
with open('${PROJECT_DIR}/.evidence/test-manifest.yaml') as f:
    d = yaml.safe_load(f)
print(d.get('test_command', ''))
")" "${JUNIT_PATH}"
    else
        # 新格式：python3 驱动——读 manifest、执行脚本、合并 JUnit，全在一个进程中
        python3 -u -c "
import subprocess, yaml, json, os, sys, xml.etree.ElementTree as ET

with open('${PROJECT_DIR}/.evidence/test-manifest.yaml') as f:
    d = yaml.safe_load(f)
tests = d.get('tests') or []
scripts = [t['script'] for t in tests if t.get('script')]

if not scripts:
    sys.exit(0)

print(f'[run-test] Loaded {len(scripts)} test script(s) from manifest', flush=True)

parts = []
for idx, script in enumerate(scripts):
    part_junit = '${JUNIT_PATH}.part.' + str(idx)
    print(f'[run-test] Running [{idx}] script={script}', flush=True)

    # 解析脚本完整路径 — 优先从项目 .evidence/ 找，找不到再从全局 evidence-tools 找
    full_script = None
    candidates = [
        os.path.join('${PROJECT_DIR}', '.evidence', script),
        os.path.join('${EVIDENCE_TOOLS}', script),
    ]
    for candidate in candidates:
        if os.access(candidate, os.X_OK):
            full_script = candidate
            break
    if not full_script:
        print(f'[run-test] ERROR: script not found in .evidence/ or evidence-tools: {script}')
        sys.exit(1)

    # 执行脚本
    env = os.environ.copy()
    env['SFP_DIR'] = '${PROJECT_DIR}'
    env['PROJECT_DIR'] = '${PROJECT_DIR}'
    r = subprocess.run(['bash', full_script, part_junit], env=env,
                       capture_output=True, text=True, timeout=120)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)

    if os.path.exists(part_junit):
        parts.append(part_junit)
        print(f'[run-test] Part written: {part_junit}', flush=True)
    else:
        print(f'[run-test] WARNING: {part_junit} not created', flush=True)

# 合并所有 part JUnit
if not parts:
    root = ET.Element('testsuites')
    ET.SubElement(root, 'testsuite', name='manifest', tests='0')
else:
    root = ET.Element('testsuites')
    for p in parts:
        try:
            t = ET.parse(p).getroot()
            root.append(t)
            os.unlink(p)
            print(f'[run-test] Merged {p}', flush=True)
        except Exception as e:
            print(f'[run-test] WARNING: could not merge {p}: {e}', flush=True)

ET.ElementTree(root).write('${JUNIT_PATH}')
print(f'[run-test] Merged JUnit written to ${JUNIT_PATH}', flush=True)
" 2>&1
    fi
elif [ -x "${EVIDENCE_TOOLS}/test-sfp.sh" ]; then
    echo "[run-test] Detected SFP integration test"
    SFP_DIR="${PROJECT_DIR}" bash "${EVIDENCE_TOOLS}/test-sfp.sh" "${JUNIT_PATH}"
else
    bash "${TEST_SELECTOR}" "${JUNIT_PATH}"
fi

if [ ! -f "${JUNIT_PATH}" ]; then
    echo "FATAL: No JUnit XML produced at ${JUNIT_PATH}" >&2
    exit 1
fi

"${EVIDENCE_TOOLS}/generate.sh" "${TASK_ID}" "${JUNIT_PATH}" "${EVIDENCE_DIR}"

echo "[INFO] 完成"
