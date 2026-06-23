#!/bin/bash
# test-sfp.sh — SFP 集成测试脚本（绝对路径版）

set -uo pipefail

OUTPUT_XML="${1:-/dev/stdout}"

# 获取真实 home 目录（不受 $HOME 覆盖影响）
REAL_HOME="$(getent passwd "$(whoami 2>/dev/null || echo "${USER:-agent}")" 2>/dev/null | cut -d: -f6)"
REAL_HOME="${REAL_HOME:-/home/agent}"

# SFP_DIR 优先走环境变量（run-test.sh 在调用时传 PROJECT_DIR），否则从真实 home 反推
SFP_DIR="${SFP_DIR:-${REAL_HOME}/.hermes/profiles/deepseek/skills/safe-file-processor}"
SFP_SCRIPTS="${SFP_DIR}/scripts"

# 前置检查
if [ ! -x "${SFP_SCRIPTS}/sfp-in" ]; then
    echo "SFP_NOT_FOUND: ${SFP_SCRIPTS}/sfp-in 不存在" >&2
    exit 1
fi

TEST_DIR="${REAL_HOME}/fast_workspace/temp/test_sfp_$$"
mkdir -p "${TEST_DIR}"

TOTAL=0
PASSED=0
FAILED=0
ERRORS=0

FAILURE_FILE="${TEST_DIR}/failures.txt"
> "${FAILURE_FILE}"
PASSED_FILE="${TEST_DIR}/passed.txt"
> "${PASSED_FILE}"

run_test() {
    local tid="$1"
    local tname="$2"
    local cmd="$3"
    local expected_prefix="$4"

    TOTAL=$((TOTAL + 1))
    echo "[RUN] ${tid}: ${tname}"

    local output
    local exit_code=0
    output=$(bash -c "$cmd" 2>&1) || exit_code=$?

    if echo "$output" | head -1 | grep -q "^${expected_prefix}"; then
        echo "[PASS] ${tid}: ${output}"
        PASSED=$((PASSED + 1))
        echo "${tid}" >> "${TEST_DIR}/passed.txt"
        return 0
    else
        echo "[FAIL] ${tid}: expected '${expected_prefix}', got '$(echo "$output" | head -1)'"
        FAILED=$((FAILED + 1))
        echo "${tid}: ${tname} — expected ${expected_prefix}, got $(echo "$output" | head -1)" >> "${FAILURE_FILE}"
        return 1
    fi
}

# T1: sfp-in 正常迁移
T1_CMD="echo 'hello sfp' > '${TEST_DIR}/t1.txt' && '${SFP_SCRIPTS}/sfp-in' '${TEST_DIR}/t1.txt'"
run_test "T1" "sfp-in 正常迁移" "$T1_CMD" "MIGRATE_OK"

# T2: sfp-in 文件不存在
T2_CMD="'${SFP_SCRIPTS}/sfp-in' '${TEST_DIR}/nonexistent_12345.txt'"
run_test "T2" "sfp-in 文件不存在" "$T2_CMD" "MIGRATE_FAIL"

# T3: sfp-process 9P红线
T3_CMD="cd /tmp && '${SFP_SCRIPTS}/sfp-process' ls"
run_test "T3" "sfp-process 9P红线" "$T3_CMD" "PROCESS_FAIL"

# T4: sfp-process 热区内执行
T4_CMD="
    echo 'process me' > '${TEST_DIR}/t4.txt' &&
    MIGRATE_OUT=\$('${SFP_SCRIPTS}/sfp-in' '${TEST_DIR}/t4.txt') &&
    HOT_DIR=\$(echo \"\$MIGRATE_OUT\" | grep -oP '${REAL_HOME}/.*?\\.sfp/hot/[0-9]+-[0-9]+-[0-9]+' | head -1) &&
    [ -n \"\$HOT_DIR\" ] &&
    cd \"\$HOT_DIR\" &&
    '${SFP_SCRIPTS}/sfp-process' cp t4.txt t4_copy.txt
"
run_test "T4" "sfp-process 热区内执行" "$T4_CMD" "PROCESS_OK"

# T5: sfp-out 空文件拒绝
T5_CMD="touch '${TEST_DIR}/empty.txt' && '${SFP_SCRIPTS}/sfp-out' '${TEST_DIR}/empty.txt'"
run_test "T5" "sfp-out 空文件拒绝" "$T5_CMD" "DELIVER_REJECT"

# T6: sfp-clean 非热区拒绝
T6_CMD="mkdir -p '${TEST_DIR}/some_dir' && '${SFP_SCRIPTS}/sfp-clean' '${TEST_DIR}/some_dir'"
run_test "T6" "sfp-clean 非热区拒绝" "$T6_CMD" "CLEAN_REJECT"

# T7: 完整4阶段工作流
T7_CMD="
    echo 'pipeline' > '${TEST_DIR}/pipeline.txt' &&
    MIGRATE_OUT=\$('${SFP_SCRIPTS}/sfp-in' '${TEST_DIR}/pipeline.txt') &&
    HOT_DIR=\$(echo \"\$MIGRATE_OUT\" | grep -oP '${REAL_HOME}/.*?\\.sfp/hot/[0-9]+-[0-9]+-[0-9]+' | head -1) &&
    [ -n \"\$HOT_DIR\" ] &&
    cd \"\$HOT_DIR\" &&
    '${SFP_SCRIPTS}/sfp-process' cp pipeline.txt pipeline_copy.txt >/dev/null &&
    '${SFP_SCRIPTS}/sfp-out' pipeline_copy.txt >/dev/null &&
    '${SFP_SCRIPTS}/sfp-clean' \"\$HOT_DIR\"
"
run_test "T7" "完整4阶段工作流" "$T7_CMD" "CLEAN_OK"

# 生成 JUnit XML
python3 -c "
from xml.dom.minidom import getDOMImplementation

impl = getDOMImplementation()
doc = impl.createDocument(None, 'testsuites', None)
root = doc.documentElement
suite = doc.createElement('testsuite')
suite.setAttribute('name', 'sfp')
suite.setAttribute('tests', str(${TOTAL}))
suite.setAttribute('failures', str(${FAILED}))
suite.setAttribute('errors', str(${ERRORS}))
suite.setAttribute('time', '1.0')

with open('${PASSED_FILE}') as pf:
    for line in pf:
        tid = line.strip()
        if not tid:
            continue
        tc = doc.createElement('testcase')
        tc.setAttribute('name', tid)
        tc.setAttribute('time', '0.1')
        suite.appendChild(tc)

with open('${FAILURE_FILE}') as ff:
    for line in ff:
        line = line.strip()
        if not line:
            continue
        parts = line.split(' — ')
        tid = parts[0].split(':')[0] if ':' in parts[0] else 'unknown'
        msg = parts[1] if len(parts) > 1 else 'failed'
        tc = doc.createElement('testcase')
        tc.setAttribute('name', tid)
        tc.setAttribute('time', '0.1')
        fail = doc.createElement('failure')
        fail.setAttribute('message', msg)
        tc.appendChild(fail)
        suite.appendChild(tc)

root.appendChild(suite)
with open('${OUTPUT_XML}', 'w') as fh:
    fh.write(doc.toxml())
"

rm -rf "${TEST_DIR}"
exit ${FAILED}
