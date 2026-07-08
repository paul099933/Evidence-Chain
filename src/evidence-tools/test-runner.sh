#!/bin/bash
# test-runner.sh — 通用声明式测试执行器
# 用法: test-runner.sh [junit_output_path]
#
# 读取项目目录下的 .evidence/test-definitions.yaml，逐条执行声明式测试，
# 输出标准 JUnit XML。
#
# 设计原则：
#   - setup / command / verify 在同一个 shell session 中执行，变量可继承
#   - 只检查 command 的 stdout 和 exit_code，不受 setup 输出干扰
set -euo pipefail

OUTPUT_XML="${1:-/dev/stdout}"
PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
DEF_FILE="${PROJECT_DIR}/.evidence/test-definitions.yaml"

[ -f "$DEF_FILE" ] || { echo "FATAL: missing $DEF_FILE" >&2; exit 1; }

python3 - "$DEF_FILE" "$OUTPUT_XML" <<'PYEOF'
import json
import os
import subprocess
import sys
import tempfile
import xml.dom.minidom as md

import yaml

def_file, out_path = sys.argv[1:3]

with open(def_file, encoding="utf-8") as f:
    defs = yaml.safe_load(f)

tests = defs.get("tests", [])
if not tests:
    print("FATAL: no tests defined", file=sys.stderr)
    sys.exit(1)

doc = md.getDOMImplementation().createDocument(None, "testsuites", None)
root = doc.documentElement
suite = doc.createElement("testsuite")
suite.setAttribute("name", defs.get("project", "declarative"))

total = passed = failed = 0


def add_case(name, ok, msg):
    tc = doc.createElement("testcase")
    tc.setAttribute("name", name)
    tc.setAttribute("time", "0.3")
    if not ok:
        fail = doc.createElement("failure")
        fail.setAttribute("message", msg)
        tc.appendChild(fail)
    suite.appendChild(tc)


for t in tests:
    tid = t["id"]
    desc = t.get("description", tid)
    total += 1
    print(f"[RUN] {tid}: {desc}", flush=True)

    setup = t.get("setup", "").strip()
    command = t.get("command", "").strip()
    verify = t.get("verify", "").strip()

    if not command:
        failed += 1
        print(f"[FAIL] {tid}: no command", file=sys.stderr)
        add_case(tid, False, "no command")
        continue

    with tempfile.TemporaryDirectory() as tmp:
        env = os.environ.copy()
        env["TEMP_DIR"] = tmp
        env["TEST_FILE"] = os.path.join(tmp, "input")
        env["TEST_CMD_OUT"] = os.path.join(tmp, "cmd.out")
        env["TEST_CMD_EXIT"] = os.path.join(tmp, "cmd.exit")
        env["TEST_VERIFY_EXIT"] = os.path.join(tmp, "verify.exit")
        env["TEST_RESULT_FILE"] = os.path.join(tmp, "result.json")

        # 在一个 bash session 中顺序执行 setup / command / verify，
        # 保证 setup 中 export 的变量可被 command 和 verify 使用。
        wrapper = f"""
set -e
{setup}
set +e
{command} > "${{TEST_CMD_OUT}}" 2>&1
echo $? > "${{TEST_CMD_EXIT}}"
{verify} > /dev/null 2>&1
echo $? > "${{TEST_VERIFY_EXIT}}"
set -e
python3 -c "
import json, os
with open(os.environ['TEST_CMD_OUT']) as f: cmd_out = f.read()
with open(os.environ['TEST_CMD_EXIT']) as f: cmd_exit = int(f.read().strip())
with open(os.environ['TEST_VERIFY_EXIT']) as f: verify_exit = int(f.read().strip())
result = {{
    'cmd_exit': cmd_exit,
    'cmd_out': cmd_out,
    'verify_failed': 1 if verify_exit != 0 else 0,
}}
with open(os.environ['TEST_RESULT_FILE'], 'w') as f:
    json.dump(result, f)
"
"""

        r = subprocess.run(
            ["bash", "-c", wrapper],
            env=env,
            capture_output=True,
            text=True,
        )

        if r.returncode != 0:
            failed += 1
            msg = f"test wrapper failed: {r.stderr.strip()[:200]}"
            print(f"[FAIL] {tid}: {msg}", file=sys.stderr)
            add_case(tid, False, msg)
            continue

        with open(env["TEST_RESULT_FILE"]) as f:
            result = json.load(f)

        cmd_out = result["cmd_out"]
        cmd_exit = result["cmd_exit"]
        verify_failed = result["verify_failed"]

        ok = True
        msg = ""
        expect = t.get("expect", {})

        if "exit_code" in expect and cmd_exit != expect["exit_code"]:
            ok, msg = False, f"exit_code expected {expect['exit_code']}, got {cmd_exit}"
        elif "stdout" in expect and cmd_out.strip() != expect["stdout"].strip():
            ok, msg = False, f"stdout mismatch: got {cmd_out[:200]!r}"
        elif "stdout_prefix" in expect and not cmd_out.startswith(expect["stdout_prefix"]):
            ok, msg = False, f"stdout_prefix expected {expect['stdout_prefix']!r}, got {cmd_out[:200]!r}"
        elif "stdout_contains" in expect and expect["stdout_contains"] not in cmd_out:
            ok, msg = False, f"stdout_contains missing {expect['stdout_contains']!r}"

        if verify_failed:
            ok, msg = False, "verify failed"

        if ok:
            passed += 1
            print(f"[PASS] {tid}")
        else:
            failed += 1
            print(f"[FAIL] {tid}: {msg}", file=sys.stderr)
        add_case(tid, ok, msg)

suite.setAttribute("tests", str(total))
suite.setAttribute("failures", str(failed))
suite.setAttribute("errors", "0")
root.appendChild(suite)

with open(out_path, "w", encoding="utf-8") as f:
    f.write(doc.toxml())

print(f"[DONE] {passed}/{total} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
PYEOF
