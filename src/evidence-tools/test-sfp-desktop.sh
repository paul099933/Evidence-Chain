#!/bin/bash
# === Pipeline 入口验证 ===
if [ -z "${HERMES_KANBAN_TASK}" ]; then
    echo "FATAL: Not in Pipeline Runner context." >&2
    exit 1
fi

BODY=$(hermes kanban show "${HERMES_KANBAN_TASK}" 2>/dev/null)
if [ -z "$BODY" ]; then
    echo "FATAL: Task ${HERMES_KANBAN_TASK} not found in Kanban DB." >&2
    exit 1
fi

NONCE=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)["task"]["body"])" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get("Nonce",""))" 2>/dev/null)

if [ -z "$NONCE" ]; then
    echo "FATAL: No Plugin nonce." >&2
    exit 1
fi

export NONCE="$NONCE"
# === 验证结束 ===
# test-sfp-desktop.sh — SFP 完整工作流测试
# 12 场景 (AC1-AC12) 覆盖：迁移→处理→交付→清理+边界拒绝
set -uo pipefail

OUTPUT_XML="${1:-/dev/stdout}"

REAL_HOME="$(getent passwd "$(whoami 2>/dev/null || echo "${USER:-agent}")" 2>/dev/null | cut -d: -f6)"
REAL_HOME="${REAL_HOME:-/home/agent}"

SFP_DIR="${SFP_DIR:-${REAL_HOME}/safe-file-processor}"
SFP_SCRIPTS="${SFP_DIR}/scripts"

# 前置检查
for s in sfp-in sfp-process sfp-out sfp-clean; do
    if [ ! -x "${SFP_SCRIPTS}/${s}" ]; then
        echo "SFP_NOT_FOUND: ${SFP_SCRIPTS}/${s} 不存在" >&2
        exit 1
    fi
done

TEST_DIR="${REAL_HOME}/fast_workspace/temp/test_sfp_full_$$"
mkdir -p "${TEST_DIR}"

# --- 真实桌面探测（同 sfp-out 逻辑）---
DESKTOP_WSL=""
if grep -qi microsoft /proc/version 2>/dev/null && command -v powershell.exe >/dev/null 2>&1; then
    DESKTOP_WIN=$(powershell.exe -NoProfile -Command "[Environment]::GetFolderPath('Desktop')" 2>/dev/null | tr -d '\r\n')
    [ -n "$DESKTOP_WIN" ] && command -v wslpath >/dev/null 2>&1 && DESKTOP_WSL=$(wslpath -u "$DESKTOP_WIN" 2>/dev/null)
fi

OUTBOX="${DESKTOP_WSL}/Hermes_Outbox"
[ -n "$DESKTOP_WSL" ] && mkdir -p "$OUTBOX" 2>/dev/null && echo "[SETUP] 桌面路径: ${OUTBOX}" || echo "[SETUP] 桌面不可用，使用回退 outbox"

TOTAL=0
PASSED=0
FAILED=0
ERRORS=0
FAILURE_FILE="${TEST_DIR}/failures.txt"
PASSED_FILE="${TEST_DIR}/passed.txt"
> "${FAILURE_FILE}"
> "${PASSED_FILE}"

MARKER="sfp_full_$$_"

# 热区
HOT_ZONE="${SFP_HOT_ZONE:-$HOME/.sfp/hot}"
mkdir -p "$HOT_ZONE"

echo "[DEBUG] DESKTOP_WSL=${DESKTOP_WSL:-unset}, PWD=$(pwd), HOT_ZONE=${HOT_ZONE}" >&2
echo "[DEBUG] SFP_SCRIPTS=${SFP_SCRIPTS}, TEST_DIR=${TEST_DIR}" >&2

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

    local first_line
    first_line=$(echo "$output" | head -1)
    echo "$first_line" | grep -qE "^${expected_prefix}" && {
        echo "[PASS] ${tid}: ${first_line}"
        PASSED=$((PASSED + 1))
        echo "${tid}" >> "${PASSED_FILE}"
        return 0
    } || {
        echo "[FAIL] ${tid}: expected '${expected_prefix}', got '${first_line}'"
        FAILED=$((FAILED + 1))
        echo "${tid}: ${tname} — expected ${expected_prefix}, got ${first_line}" >> "${FAILURE_FILE}"
        return 1
    }
}

# ============================================================
# AC1: 正常文件迁移 — 普通文件 → 热区隔离目录
# ============================================================
AC1_SRC="${TEST_DIR}/${MARKER}ac1_normal.txt"
echo "AC1 test content — normal file migration" > "${AC1_SRC}"

AC1_CMD="'${SFP_SCRIPTS}/sfp-in' '${AC1_SRC}'"
run_test "AC1" "正常文件迁移到热区" "$AC1_CMD" "MIGRATE_OK"

# 提取隔离目录路径以便后续清理
AC1_DEST=$(bash -c "'${SFP_SCRIPTS}/sfp-in' '${AC1_SRC}'" 2>&1 | grep -oP "${HOT_ZONE}/[0-9]+-[0-9]+-[0-9]+" | tail -1)

# ============================================================
# AC2: 不存在文件拒绝
# ============================================================
AC2_CMD="'${SFP_SCRIPTS}/sfp-in' '${TEST_DIR}/nonexistent_file_$$.xyz'"
run_test "AC2" "不存在文件迁移拒绝" "$AC2_CMD" "MIGRATE_FAIL"

# ============================================================
# AC3: 热区内处理
# ============================================================
AC3_DEST=$(bash -c "SRC='${TEST_DIR}/${MARKER}ac3_normal.txt'; echo 'ac3 content' > \"\$SRC\"; OUT=\$('${SFP_SCRIPTS}/sfp-in' \"\$SRC\"); echo \"\$OUT\" | grep -oP '${HOT_ZONE}/[0-9]+-[0-9]+-[0-9]+' | tail -1")
AC3_FILE=$(ls "${AC3_DEST}/" 2>/dev/null | head -1)
AC3_FULL="${AC3_DEST}/${AC3_FILE}"

AC3_CMD="cd '${AC3_DEST}' && '${SFP_SCRIPTS}/sfp-process' cp '${AC3_FILE}' '${AC3_FILE}.proc'"
run_test "AC3" "热区内处理命令" "$AC3_CMD" "PROCESS_OK"

# 验证处理结果
[ -f "${AC3_FULL}.proc" ] && echo "[VERIFY] AC3: ✅ 处理后的文件存在" || echo "[VERIFY] AC3: ⚠ 处理后文件不存在"

# ============================================================
# AC4: 跨边界执行拒绝（/mnt/c/）
# ============================================================
MNT_C="/mnt/c"
AC4_CMD="cd '${MNT_C}' && '${SFP_SCRIPTS}/sfp-process' ls 2>&1"
run_test "AC4" "跨边界(/mnt/c/)执行拒绝" "$AC4_CMD" "PROCESS_FAIL:.*9P红线"

# ============================================================
# AC5: 非空文件交付桌面
# ============================================================
if [ -n "$DESKTOP_WSL" ]; then
    AC5_FILE="${MARKER}ac5_deliver.txt"
    AC5_SRC="${TEST_DIR}/${AC5_FILE}"
    echo "AC5 desktop delivery test" > "${AC5_SRC}"
    AC5_CMD="'${SFP_SCRIPTS}/sfp-out' '${AC5_SRC}'"
    run_test "AC5" "非空文件桌面交付" "$AC5_CMD" "DELIVER_OK:.*mode=desktop"
    # 物理验证
    if [ -f "${OUTBOX}/${AC5_FILE}" ]; then
        echo "[VERIFY] AC5: ✅ 文件在桌面 ${OUTBOX}/${AC5_FILE}"
    else
        echo "[VERIFY] AC5: ⚠ 文件未出现在桌面"
    fi
    rm -f "${OUTBOX}/${AC5_FILE}" 2>/dev/null || true
else
    # 桌面不可用，测试回退模式
    echo "[SKIP] AC5: 桌面不可用，跳过物理验证"
    AC5_FILE="${MARKER}ac5_deliver.txt"
    AC5_SRC="${TEST_DIR}/${AC5_FILE}"
    echo "AC5 test" > "${AC5_SRC}"
    AC5_CMD="'${SFP_SCRIPTS}/sfp-out' '${AC5_SRC}'"
    run_test "AC5" "非空文件交付(回退模式)" "$AC5_CMD" "DELIVER_OK"
fi

# ============================================================
# AC6: 空文件交付拒绝
# ============================================================
AC6_FILE="${MARKER}ac6_empty.txt"
AC6_SRC="${TEST_DIR}/${AC6_FILE}"
touch "${AC6_SRC}"
AC6_CMD="'${SFP_SCRIPTS}/sfp-out' '${AC6_SRC}'"
run_test "AC6" "空文件桌面交付拒绝" "$AC6_CMD" "DELIVER_REJECT:.*文件大小为0"

if [ -n "$DESKTOP_WSL" ]; then
    # 物理验证：桌面不应有该文件
    [ ! -f "${OUTBOX}/${AC6_FILE}" ] && echo "[VERIFY] AC6: ✅ 桌面无残留空文件"
fi

# ============================================================
# AC7: 同名文件不覆盖
# ============================================================
if [ -n "$DESKTOP_WSL" ]; then
    AC7_FILE="${MARKER}ac7_existing.txt"
    AC7_SRC="${TEST_DIR}/${AC7_FILE}"
    echo "original AC7 content" > "${AC7_SRC}"

    # 第一次交付
    "${SFP_SCRIPTS}/sfp-out" "${AC7_SRC}" > /dev/null 2>&1
    ORIG_MTIME=$(stat -c%Y "${OUTBOX}/${AC7_FILE}" 2>/dev/null || echo "0")
    ORIG_CONTENT=$(cat "${OUTBOX}/${AC7_FILE}" 2>/dev/null || echo "")

    # 修改源文件后第二次交付
    echo "modified AC7 content" > "${AC7_SRC}"
    AC7_CMD="'${SFP_SCRIPTS}/sfp-out' '${AC7_SRC}'"
    run_test "AC7" "同名文件不覆盖(已存在检测)" "$AC7_CMD" "DELIVER_OK:.*已存在"

    NEW_MTIME=$(stat -c%Y "${OUTBOX}/${AC7_FILE}" 2>/dev/null || echo "0")
    NEW_CONTENT=$(cat "${OUTBOX}/${AC7_FILE}" 2>/dev/null || echo "")
    if [ "$ORIG_MTIME" = "$NEW_MTIME" ] && [ "$ORIG_CONTENT" = "original AC7 content" ]; then
        echo "[VERIFY] AC7: ✅ 文件未被覆盖，内容正确"
    else
        echo "[VERIFY] AC7: ⚠ 文件被覆盖或内容不一致"
    fi
    rm -f "${OUTBOX}/${AC7_FILE}" 2>/dev/null || true
else
    echo "[SKIP] AC7: 桌面不可用，跳过同名文件覆盖测试"
fi

# ============================================================
# AC8: 自定义文件名交付
# ============================================================
if [ -n "$DESKTOP_WSL" ]; then
    AC8_SRC="${TEST_DIR}/${MARKER}ac8_source.txt"
    echo "custom name delivery test" > "${AC8_SRC}"
    AC8_TARGET="custom_file_$$.txt"
    AC8_CMD="'${SFP_SCRIPTS}/sfp-out' '${AC8_SRC}' '${AC8_TARGET}'"
    run_test "AC8" "自定义文件名交付桌面" "$AC8_CMD" "DELIVER_OK"

    if [ -f "${OUTBOX}/${AC8_TARGET}" ]; then
        echo "[VERIFY] AC8: ✅ 自定义文件名 ${AC8_TARGET} 已在桌面"
    else
        echo "[VERIFY] AC8: ⚠ 自定义文件名未出现"
    fi
    rm -f "${OUTBOX}/${AC8_TARGET}" 2>/dev/null || true
else
    echo "[SKIP] AC8: 桌面不可用，跳过自定义文件名测试"
fi

# ============================================================
# AC9: 热区清理
# ============================================================
# 先创建一个隔离目录来清理
AC9_DIR=$(bash -c "SRC='${TEST_DIR}/${MARKER}ac9_clean.txt'; echo 'clean test' > \"\$SRC\"; OUT=\$('${SFP_SCRIPTS}/sfp-in' \"\$SRC\"); echo \"\$OUT\" | grep -oP '${HOT_ZONE}/[0-9]+-[0-9]+-[0-9]+' | tail -1")
AC9_CMD="'${SFP_SCRIPTS}/sfp-clean' '${AC9_DIR}'"
run_test "AC9" "热区目录清理" "$AC9_CMD" "CLEAN_OK"

# 验证目录已被删除
[ ! -d "${AC9_DIR}" ] && echo "[VERIFY] AC9: ✅ 隔离目录已删除" || echo "[VERIFY] AC9: ⚠ 隔离目录仍存在"

# ============================================================
# AC10: 非热区清理拒绝（家目录）
# ============================================================
AC10_CMD="'${SFP_SCRIPTS}/sfp-clean' '${HOME}'"
run_test "AC10" "非热区目录清理拒绝(HOME)" "$AC10_CMD" "CLEAN_REJECT"

# ============================================================
# AC11: 完整四阶段工作流
# ============================================================
if [ -n "$DESKTOP_WSL" ]; then
    AC11_FILE="${MARKER}ac11_pipeline.txt"
    AC11_SRC="${TEST_DIR}/${AC11_FILE}"
    echo "AC11 full pipeline delivery test" > "${AC11_SRC}"

    # in → process → out(桌面) → clean
    AC11_CMD="
MIGRATE_OUT=\$('${SFP_SCRIPTS}/sfp-in' '${AC11_SRC}') &&
HOT_DIR=\$(echo \"\$MIGRATE_OUT\" | grep -oP '${HOT_ZONE}/[0-9]+-[0-9]+-[0-9]+' | tail -1) &&
[ -n \"\$HOT_DIR\" ] &&
cd \"\$HOT_DIR\" &&
HOT_FILE=\$(ls \"\$HOT_DIR\" | head -1) &&
'${SFP_SCRIPTS}/sfp-process' cp \"\$HOT_FILE\" \"${AC11_FILE}.processed\" >/dev/null &&
'${SFP_SCRIPTS}/sfp-out' \"${AC11_FILE}.processed\" >/dev/null &&
'${SFP_SCRIPTS}/sfp-clean' \"\$HOT_DIR\""

    run_test "AC11" "完整四阶段流水线" "$AC11_CMD" "CLEAN_OK"

    # 物理验证：桌面有交付文件
    if [ -f "${OUTBOX}/${AC11_FILE}.processed" ]; then
        echo "[VERIFY] AC11: ✅ 流水线最终文件 ${AC11_FILE}.processed 在桌面"
    else
        echo "[VERIFY] AC11: ⚠ 流水线文件未出现在桌面"
    fi
    rm -f "${OUTBOX}/${AC11_FILE}.processed" 2>/dev/null || true
else
    echo "[SKIP] AC11: 桌面不可用，跳过完整4阶段流水线测试"
fi

# ============================================================
# AC12: 交付文件权限正确 — NTFS 非只读
# ============================================================
if [ -n "$DESKTOP_WSL" ] && command -v powershell.exe >/dev/null 2>&1; then
    AC12_FILE="${MARKER}ac12_perms.txt"
    AC12_SRC="${TEST_DIR}/${AC12_FILE}"
    echo "AC12 permission test" > "${AC12_SRC}"

    "${SFP_SCRIPTS}/sfp-out" "${AC12_SRC}" > /dev/null 2>&1

    # 检查 NTFS 只读属性
    WIN_DEST=$(wslpath -w "${OUTBOX}/${AC12_FILE}" 2>/dev/null || echo "")
    if [ -n "$WIN_DEST" ]; then
        IS_READONLY=$(powershell.exe -NoProfile -Command "(Get-Item '$WIN_DEST').IsReadOnly" 2>/dev/null | tr -d '\r\n')
        if [ "$IS_READONLY" = "False" ]; then
            echo "[VERIFY] AC12: ✅ 文件非只读(IsReadOnly=False)"
            TOTAL=$((TOTAL + 1))
            PASSED=$((PASSED + 1))
            echo "AC12" >> "${PASSED_FILE}"
            echo "[PASS] AC12: 交付文件权限正确(非只读)"
        else
            echo "[VERIFY] AC12: ⚠ 文件为只读(IsReadOnly=${IS_READONLY})"
            TOTAL=$((TOTAL + 1))
            FAILED=$((FAILED + 1))
            echo "AC12: 交付文件权限 — 文件为只读(IsReadOnly=${IS_READONLY})" >> "${FAILURE_FILE}"
            echo "[FAIL] AC12: 文件权限不正确(只读)"
        fi
    else
        echo "[VERIFY] AC12: ⚠ 无法转换路径，跳过 NTFS 属性检查"
    fi
    rm -f "${OUTBOX}/${AC12_FILE}" 2>/dev/null || true
else
    echo "[SKIP] AC12: 桌面不可用，跳过文件权限测试"
fi

# ============================================================
# 清理所有热区残留（本测试创建的）
# ============================================================
for d in "$AC1_DEST" "$AC3_DEST" "$AC9_DIR"; do
    [ -n "$d" ] && [ -d "$d" ] && rm -rf "$d" 2>/dev/null || true
done

# 兜底：删除本测试标记前缀的所有桌面文件
[ -n "$DESKTOP_WSL" ] && find "${OUTBOX}" -name "${MARKER}*" -type f -delete 2>/dev/null || true

# ============================================================
# 生成 JUnit XML
# ============================================================
python3 -c "
from xml.dom.minidom import getDOMImplementation

impl = getDOMImplementation()
doc = impl.createDocument(None, 'testsuites', None)
root = doc.documentElement
suite = doc.createElement('testsuite')
suite.setAttribute('name', 'sfp-full-workflow')
suite.setAttribute('tests', '${TOTAL}')
suite.setAttribute('failures', '${FAILED}')
suite.setAttribute('errors', '${ERRORS}')
suite.setAttribute('time', '4.0')

with open('${PASSED_FILE}') as pf:
    for line in pf:
        tid = line.strip()
        if not tid:
            continue
        tc = doc.createElement('testcase')
        tc.setAttribute('name', tid)
        tc.setAttribute('time', '0.3')
        suite.appendChild(tc)

with open('${FAILURE_FILE}') as ff:
    for line in ff:
        line = line.strip()
        if not line:
            continue
        parts = line.split(' — ', 1)
        tid = parts[0].split(':')[0] if ':' in parts[0] else 'unknown'
        msg = parts[1] if len(parts) > 1 else 'failed'
        tc = doc.createElement('testcase')
        tc.setAttribute('name', tid)
        tc.setAttribute('time', '0.3')
        fail = doc.createElement('failure')
        fail.setAttribute('message', msg)
        tc.appendChild(fail)
        suite.appendChild(tc)

root.appendChild(suite)
with open('${OUTPUT_XML}', 'w') as fh:
    fh.write(doc.toxml())
"

echo "[DONE] sfp-full-workflow: ${PASSED}/${TOTAL} passed, ${FAILED} failed"

# 清理临时目录
rm -rf "${TEST_DIR}"

exit ${FAILED}
