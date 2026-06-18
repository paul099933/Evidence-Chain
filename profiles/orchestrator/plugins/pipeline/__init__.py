"""
Pipeline Orchestrator Plugin — Evidence-Chain Path B.

Registers ``pipeline_start`` under the ``kanban`` toolset so that any
orchestrator profile with ``toolsets: [kanban, ...]`` sees it automatically.

State machine (all in code, no SOUL.md logic):

    pipeline_start(args)
      │
      ├─ git stash → branch → worktree
      │
      └─ loop (retry_count ≤ max_retries)
           │
           ├─ kanban_create(assignee=runner, …)
           ├─ poll_until_done(runner_id)
           ├─ code: iterate acceptance_criteria ?
           │    ├─ YES → cleanup, return {"verdict": "pass"}
           │    └─ NO  → retry_count++
           │             if exhausted → return {"verdict": "retry_exhausted"}
           │             kanban_create(assignee=fixer, …)
           │             poll_until_done(fixer_id)
           │             loop
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

PIPELINE_START_SCHEMA = {
    "name": "pipeline_start",
    "description": (
        "启动完整测试-修复 Pipeline。接收项目路径、测试脚本列表、验收标准，"
        "自动创建 Runner→Fixer 循环，返回带 SHA-256 的物理证据。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_dir": {
                "type": "string",
                "description": "项目绝对路径（必须有 .evidence/test-manifest.yaml）",
            },
            "test_scripts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "测试脚本名列表，如 ['test-sfp.sh', 'test-empty-reject.sh']",
            },
            "test_spec": {
                "type": "string",
                "description": "用户意图描述，用于日志和 Fixer 上下文",
            },
            "acceptance_criteria": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "description": {"type": "string"},
                        "check": {"type": "string", "enum": ["test_pass"]},
                        "test_id": {"type": "string"},
                    },
                    "required": ["id", "description"],
                },
                "description": "验收标准条目清单，Plugin 逐条遍历检查",
            },
            "scope": {
                "type": "object",
                "description": "Fixer 修改范围约束",
                "properties": {
                    "allow_edit": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "允许修改的文件 glob",
                    },
                    "deny_edit": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "禁止修改的文件 glob",
                    },
                    "max_diff_lines": {
                        "type": "integer",
                        "description": "最大修改行数",
                        "default": 50,
                    },
                },
            },
            "max_retries": {
                "type": "integer",
                "description": "最大修复重试次数（默认 3）",
                "default": 3,
            },
        },
        "required": ["project_dir", "test_spec"],
    },
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_EVIDENCE_TOOLS = os.environ.get(
    "EVIDENCE_TOOLS",
    "/home/agent/.hermes/evidence-tools",
)

REAL_HOME = "/home/agent"
if os.environ.get("HERMES_PROFILE"):
    try:
        r = subprocess.run(
            ["getent", "passwd", os.environ.get("USER", "agent")],
            capture_output=True, text=True, timeout=5,
        )
        if r.stdout.strip():
            REAL_HOME = r.stdout.strip().split(":")[5]
    except Exception:
        pass
else:
    REAL_HOME = os.environ.get("HOME", "/home/agent")
"""Fallback to real home when profile overrides $HOME (evidence-chain pitfall #7)."""


def _check_call(cmd: list[str], cwd: str | None = None) -> str:
    """Run a command, raise on failure, return stdout."""
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(
            f"{' '.join(cmd)} failed (exit={r.returncode}):\n"
            f"  stdout: {r.stdout.strip()}\n"
            f"  stderr: {r.stderr.strip()}"
        )
    return r.stdout.strip()


def _git(*args: str, cwd: str | None = None) -> str:
    return _check_call(["git"] + list(args), cwd=cwd)


def _create_kanban_task(
    title: str,
    assignee: str,
    workspace_kind: str,
    workspace_path: str,
    body: str,
) -> str:
    """Create a kanban task and return its task_id."""
    from tools.kanban_tools import _handle_create

    result = _handle_create({
        "title": title,
        "assignee": assignee,
        "workspace_kind": workspace_kind,
        "workspace_path": workspace_path,
        "body": body,
    })
    data = json.loads(result)
    if not data.get("ok"):
        raise RuntimeError(f"kanban_create failed: {data}")
    task_id: str = data["task_id"]
    logger.info("Created kanban task %s (assignee=%s)", task_id, assignee)
    return task_id


def _extract_counts(text: str) -> tuple[Optional[int], Optional[int]]:
    """Extract passed/failed counts from free text.

    Generic patterns — no project-specific strings (SFP, T1-T7, etc.).
    Accepts Chinese and English keywords.
    """
    import re
    passed: Optional[int] = None
    failed: Optional[int] = None

    # Pattern 1: "N/M" fraction — most common test output format
    m = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if m:
        passed = int(m.group(1))
        total = int(m.group(2))
        failed = total - passed

    # Pattern 2: explicit "passed: N" / "通过: N"
    m = re.search(r"(?:passed|通过|pass)\D{0,5}?(\d+)", text, re.IGNORECASE)
    if m:
        passed = int(m.group(1))

    # Pattern 3: explicit "failed: N" / "失败: N" / "fail: N"
    m = re.search(r"(?:failed|失败|fail|error|错误)\D{0,5}?(\d+)", text, re.IGNORECASE)
    if m:
        failed = int(m.group(1))

    return passed, failed


def _poll_until_done(task_id: str, timeout: int = 600) -> dict:
    """Poll until task is done, return evidence from the most reliable source.

    Resolution order:
      1. Filesystem:  ~/.hermes/evidence-archive/{task_id}/evidence.json
         (run-test.sh writes this — cannot be bypassed by the LLM)
      2. Kanban metadata:  runs[0].metadata.evidence
         (written by kanban_complete — may be skipped by the LLM)
      3. Summary text:     extract passed/failed numbers via regex
         (summary is required by kanban_complete — always present)
    """
    from tools.registry import registry

    evidence_root = os.path.join(
        os.environ.get("REAL_HOME", "/home/agent"),
        ".hermes", "evidence-archive", task_id,
    )
    evidence_json = os.path.join(evidence_root, "evidence.json")

    start = time.time()
    while time.time() - start < timeout:
        raw = registry.dispatch("kanban_show", {"task_id": task_id})
        data = json.loads(raw)
        status = data.get("task", {}).get("status")

        # 如果任务仍为 ready，触发一次 dispatch（兼容 CLI 模式无后台调度器）
        if status == "ready":
            try:
                subprocess.run(
                    ["hermes", "kanban", "dispatch", "--max", "10"],
                    capture_output=True, text=True, timeout=10,
                )
            except Exception:
                pass

        runs = data.get("runs", []) or []

        # --- Source 1: filesystem (strongest) ---
        if os.path.isfile(evidence_json):
            try:
                with open(evidence_json) as f:
                    fs_evidence = json.load(f)
                # === nonce 校验：证据必须绑定到当前 task ===
                body_str = data.get("task", {}).get("body", "{}")
                body_json = json.loads(body_str)
                expected_nonce = body_json.get("Nonce", "")
                if expected_nonce and fs_evidence.get("nonce") != expected_nonce:
                    raise RuntimeError(
                        f"Evidence nonce mismatch for task {task_id}: "
                        f"evidence={fs_evidence.get('nonce')}, expected={expected_nonce}"
                    )
                if "passed" in fs_evidence or "failed" in fs_evidence:
                    return fs_evidence
            except (json.JSONDecodeError, OSError):
                pass

        # --- Source 2: kanban metadata (medium) ---
        for r in runs:
            meta = r.get("metadata") or {}
            # 嵌套格式: metadata.evidence.passed
            ev = meta.get("evidence") or {}
            if "passed" in ev or "failed" in ev:
                return ev
            # 平铺格式: metadata.passed / metadata.failed
            if "passed" in meta or "failed" in meta:
                return {
                    "passed": meta.get("passed", 0),
                    "failed": meta.get("failed", 0),
                    "sha256": meta.get("sha256", ""),
                }

        # Task still running — keep polling
        if status not in ("done", "blocked", "archived"):
            time.sleep(15)
            continue

        # Task is terminal — try source 3
        if status == "done":
            for r in runs:
                summary = r.get("summary") or ""
                passed, failed = _extract_counts(summary)
                if passed is not None or failed is not None:
                    return {
                        "passed": passed or 0,
                        "failed": failed or 0,
                        "source": "summary_text",
                    }

        # Blocked / archived or totally unparseable
        if status in ("blocked", "archived"):
            raise RuntimeError(
                f"Task {task_id} entered terminal state '{status}' "
                f"before completion"
            )

        # Task done but no evidence found anywhere — return zeros
        return {"passed": 0, "failed": 0, "source": "unknown"}

    raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")


def _init_branch(project_dir: str) -> tuple[str, str]:
    """Stash, create branch, return (branch_name, ws_root)."""
    branch = f"fix/pipeline-{int(time.time())}"
    ws_root = f"/tmp/evidence-chain/{branch}"

    _git("stash", "push", "--include-untracked",
         "-m", f"evidence-chain-clean-{branch}",
         cwd=project_dir)
    _git("branch", branch, "HEAD", cwd=project_dir)
    Path(ws_root).mkdir(parents=True, exist_ok=True)

    logger.info("Created branch=%s ws_root=%s", branch, ws_root)
    return branch, ws_root


def _cleanup(ws_root: str) -> None:
    """Idempotent cleanup of worktree directories."""
    import shutil
    shutil.rmtree(ws_root, ignore_errors=True)
    logger.info("Cleaned up %s", ws_root)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def handle_pipeline_start(args: dict, **kw) -> str:
    """Execute the full test-verify-fix pipeline loop."""
    project_dir: str = args["project_dir"]
    test_spec: str = args["test_spec"]
    acceptance_criteria: list[dict] = args.get("acceptance_criteria") or []
    max_retries: int = args.get("max_retries") or 3
    test_scripts: list[str] = args.get("test_scripts") or []

    # scope: allow_edit/deny_edit 嵌套在 scope 内（v1.1），兼容旧格式顶层传递
    scope: dict = args.get("scope") or {}
    allow_edit: list[str] = scope.get("allow_edit") or args.get("allow_edit") or []
    deny_edit: list[str] = scope.get("deny_edit") or args.get("deny_edit") or []

    # Validate
    if not os.path.isdir(project_dir):
        return json.dumps({"error": f"project_dir does not exist: {project_dir}"})
    if not os.path.isdir(os.path.join(project_dir, ".git")):
        return json.dumps({"error": f"project_dir is not a git repo: {project_dir}"})

    # === L1: 防预污染检查 ===
    r = subprocess.run(
        ["git", "-C", project_dir, "status", "--short"],
        capture_output=True, text=True, timeout=5,
    )
    if r.stdout.strip():
        return json.dumps({
            "error": f"PROJECT_DIRTY: project has uncommitted changes before pipeline_start:\n{r.stdout.strip()}"
        })

    r = subprocess.run(
        ["git", "-C", project_dir, "status", "--untracked-files=all", "--short"],
        capture_output=True, text=True, timeout=5,
    )
    untracked = [line for line in r.stdout.strip().split('\n') if line.startswith('??')]
    if untracked:
        return json.dumps({
            "error": f"PROJECT_UNTRACKED: {untracked}\nOrchestrator must not create files before pipeline_start."
        })
    # === 检查结束 ===

    # Phase 0 — prepare branch
    try:
        branch, ws_root = _init_branch(project_dir)
    except Exception as e:
        return json.dumps({"error": f"branch init failed: {e}"})

    # Phase 0b — persist acceptance criteria for Fixer
    if acceptance_criteria:
        ac_path = os.path.join(project_dir, ".evidence", "acceptance_criteria.json")
        os.makedirs(os.path.dirname(ac_path), exist_ok=True)
        with open(ac_path, "w") as f:
            json.dump(acceptance_criteria, f, ensure_ascii=False, indent=2)
        logger.info("Wrote %s (%d criteria)", ac_path, len(acceptance_criteria))

    evidence_history: list[dict] = []
    retry_count = 0
    nonce = secrets.token_hex(16)

    while retry_count <= max_retries:
        # Scope JSON: Runner gets a minimal subset (no allow_edit — pitfall #12)
        runner_scope = {
            "acceptance_criteria": acceptance_criteria,
            "retry_count": retry_count,
            "max_retries": max_retries,
            "baseline_passed": 0,
            "test_scripts": test_scripts,
            "nonce": nonce,
        }
        # Fixer gets the full scope
        fixer_scope = {
            "acceptance_criteria": acceptance_criteria,
            "retry_count": retry_count,
            "max_retries": max_retries,
            "allow_edit": allow_edit,
            "deny_edit": deny_edit,
        }

        runner_id = _create_kanban_task(
            title=f"Run tests: {test_spec} (retry {retry_count})",
            assignee="runner",
            workspace_kind="worktree",
            workspace_path=f"{ws_root}/runner-ws-retry-{retry_count}",
            body=json.dumps({
                "Branch": branch,
                "Project": project_dir,
                "Retry": retry_count,
                "Spec": test_spec,
                "Scope": runner_scope,
                "TestScripts": test_scripts,
                "Nonce": nonce,
            }, ensure_ascii=False),
        )
        logger.info(
            "Runner task %s dispatched (retry %d/%d)",
            runner_id, retry_count, max_retries,
        )

        # --- Poll Runner ---
        evidence = _poll_until_done(runner_id)

        # --- Code-level decision: iterate acceptance criteria ---
        failed_gates: list[str] = []
        for c in acceptance_criteria:
            check_type = c.get("check", "test_pass")
            if check_type == "test_pass":
                # 优先用 test_id，兼容旧格式只用 id 的条目
                tid = c.get("test_id") or c.get("id")
                if not tid:
                    continue  # 纯描述性条目，不检查
                tests = evidence.get("tests", [])
                test = next(
                    (t for t in tests if t.get("id") == tid or t.get("name") == tid),
                    None,
                )
                if test is None or test.get("status") != "pass":
                    failed_gates.append(c["id"])
                    logger.info("Gate %s failed: %s", c["id"], c.get("description", ""))

        verdict = "pass" if not failed_gates else None

        # 证据入栈
        evidence_history.append(evidence)

        if verdict == "pass":
            _cleanup(ws_root)
            return json.dumps({
                "verdict": "pass",
                "branch": branch,
                "evidence": evidence,
                "retry_count": retry_count,
                "failed_gates": failed_gates,
            }, ensure_ascii=False)

        # Failed — check retry budget
        retry_count += 1
        if retry_count > max_retries:
            _cleanup(ws_root)
            return json.dumps({
                "verdict": "retry_exhausted",
                "branch": branch,
                "evidence": evidence,
                "evidence_history": evidence_history,
                "retry_count": retry_count - 1,
                "failed_gates": failed_gates,
            }, ensure_ascii=False)

        # --- Create Fixer ---
        fixer_id = _create_kanban_task(
            title=f"Fix: {test_spec} (retry {retry_count})",
            assignee="fixer",
            workspace_kind="worktree",
            workspace_path=f"{ws_root}/fixer-ws-retry-{retry_count}",
            body=json.dumps({
                "Branch": branch,
                "Project": project_dir,
                "Retry": retry_count,
                "Spec": test_spec,
                "Evidence": evidence,
                "Scope": fixer_scope,
            }, ensure_ascii=False),
        )
        logger.info("Fixer task %s dispatched (retry %d/%d)", fixer_id, retry_count, max_retries)

        # --- Poll Fixer ---
        _poll_until_done(fixer_id)
        # Fixer commits; next Runner on same branch picks up the fix

        # Loop back to create new Runner

    # Unreachable — handled above, but keep as safety net
    return json.dumps({"error": "unexpected exit from pipeline loop"})


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Called by PluginManager when the plugin is loaded."""
    ctx.register_tool(
        name="pipeline_start",
        toolset="kanban",
        schema=PIPELINE_START_SCHEMA,
        handler=handle_pipeline_start,
        description=(
            "Full test-verify-fix pipeline. "
            "Handles branch creation, task dispatch, polling, "
            "pass/fail decisions, and retry budget entirely in code."
        ),
    )
    logger.info("pipeline plugin loaded: pipeline_start registered under kanban")
