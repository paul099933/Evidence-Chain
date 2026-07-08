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
           │             diff_guard check scope
           │             loop
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

from pipeline_core import acceptance, diff_guard, git_utils
from pipeline_core import evidence as evidence_ops

# Ensure ~/.hermes is on sys.path so pipeline_core can be imported after deploy.
_HERMES_HOME = Path.home() / ".hermes"
if str(_HERMES_HOME) not in sys.path:
    sys.path.insert(0, str(_HERMES_HOME))

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

PIPELINE_START_SCHEMA = {
    "name": "pipeline_start",
    "description": (
        "启动完整测试-修复 Pipeline。接收项目路径、验收标准，"
        "自动创建 Runner→Fixer 循环，返回带 SHA-256 的物理证据。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_dir": {
                "type": "string",
                "description": "项目绝对路径（必须有 .evidence/test-manifest.yaml）",
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
                        "description": "允许修改的文件 glob；空列表=禁止所有文件",
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

REAL_HOME = git_utils.REAL_HOME


def _create_kanban_task(
    title: str,
    assignee: str,
    workspace_kind: str,
    workspace_path: str,
    body: str,
) -> str:
    """Create a kanban task and return its task_id."""
    from tools.kanban_tools import _handle_create

    result = _handle_create(
        {
            "title": title,
            "assignee": assignee,
            "workspace_kind": workspace_kind,
            "workspace_path": workspace_path,
            "body": body,
        }
    )
    data = json.loads(result)
    if not data.get("ok"):
        raise RuntimeError(f"kanban_create failed: {data}")
    task_id: str = data["task_id"]
    logger.info("Created kanban task %s (assignee=%s)", task_id, assignee)
    return task_id


def _poll_until_done(task_id: str, timeout: int = 600) -> dict:
    """Poll until task is done and return filesystem evidence.

    Only evidence.json written by run-test.sh is authoritative.
    Kanban metadata / summary text are kept for diagnostics only.
    """
    from tools.registry import registry

    evidence_root = os.path.join(
        REAL_HOME,
        ".hermes",
        "evidence-archive",
        task_id,
    )
    evidence_json = os.path.join(evidence_root, "evidence.json")

    start = time.time()
    last_status = None
    last_data: dict = {}

    while time.time() - start < timeout:
        raw = registry.dispatch("kanban_show", {"task_id": task_id})
        data = json.loads(raw)
        last_data = data
        status = data.get("task", {}).get("status")
        last_status = status

        # 如果任务仍为 ready，触发一次 dispatch（兼容 CLI 模式无后台调度器）
        if status == "ready":
            try:
                subprocess.run(
                    ["hermes", "kanban", "dispatch", "--max", "10"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except Exception:
                pass

        # --- Authoritative source: filesystem evidence.json ---
        if os.path.isfile(evidence_json):
            try:
                ev, validation_errors = evidence_ops.load_and_validate(evidence_root)
            except (json.JSONDecodeError, OSError, ValueError) as e:
                raise RuntimeError(
                    f"Task {task_id}: evidence.json exists but cannot be loaded/validated: {e}"
                )

            body_str = data.get("task", {}).get("body", "{}")
            try:
                body_json = json.loads(body_str)
            except json.JSONDecodeError:
                body_json = {}
            expected_nonce = body_json.get("Nonce", "")
            if expected_nonce and ev.get("nonce") != expected_nonce:
                raise RuntimeError(
                    f"Evidence nonce mismatch for task {task_id}: "
                    f"evidence={ev.get('nonce')}, expected={expected_nonce}"
                )
            if validation_errors:
                raise RuntimeError(
                    f"Evidence validation failed for task {task_id}: {validation_errors}"
                )
            return ev

        # Task is terminal but no evidence file -> failure.
        if status in ("done", "blocked", "archived"):
            break

        time.sleep(15)

    # Build diagnostic message from secondary sources.
    runs = last_data.get("runs", []) or []
    diagnostic_parts: list[str] = [f"status={last_status}"]
    if runs:
        last_run = runs[-1]
        summary = last_run.get("summary") or ""
        meta = last_run.get("metadata") or {}
        diagnostic_parts.append(f"summary={summary!r}")
        diagnostic_parts.append(f"metadata_keys={sorted(meta.keys())}")
    diagnostic = "; ".join(diagnostic_parts)

    raise RuntimeError(
        f"Task {task_id} completed or timed out without producing a valid "
        f"evidence.json at {evidence_json}. {diagnostic}"
    )


def _create_verifier(
    parents: list[str],
    branch: str,
    project_dir: str,
    retry_count: int,
    evidence: dict,
    scope: dict,
    failed_gates: list[str],
) -> str:
    """Create a verifier kanban task and return its task_id."""
    from tools.kanban_tools import _handle_create

    result = _handle_create(
        {
            "title": f"Audit fix: retry {retry_count}",
            "assignee": "verifier",
            "parents": parents,
            "body": json.dumps(
                {
                    "Branch": branch,
                    "Project": project_dir,
                    "Retry": retry_count,
                    "Evidence": evidence,
                    "Scope": scope,
                    "PrevFailedGates": failed_gates,
                },
                ensure_ascii=False,
            ),
        }
    )
    data = json.loads(result)
    if not data.get("ok"):
        raise RuntimeError(f"kanban_create (verifier) failed: {data}")
    task_id: str = data["task_id"]
    logger.info("Created verifier task %s (retry %d)", task_id, retry_count)
    return task_id


def _poll_verdict(task_id: str, timeout: int = 300) -> dict:
    """Poll verifier task and return its audit verdict metadata.

    Unlike _poll_until_done which reads evidence.json,
    this reads the kanban metadata verdict field.
    """
    from tools.registry import registry

    start = time.time()
    while time.time() - start < timeout:
        raw = registry.dispatch("kanban_show", {"task_id": task_id})
        data = json.loads(raw)
        status = data.get("task", {}).get("status")
        runs = data.get("runs", []) or []

        for r in runs:
            meta = r.get("metadata") or {}
            if meta.get("verdict") in ("audit_pass", "audit_block"):
                return meta

        if status == "blocked":
            return {"verdict": "audit_block", "block_reasons": ["kanban_blocked"]}

        if status not in ("done", "blocked", "archived"):
            time.sleep(10)
            continue

        raise TimeoutError(f"Verifier task {task_id} did not complete within {timeout}s")


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def handle_pipeline_start(args: dict, **kw) -> str:
    """Execute the full test-verify-fix pipeline loop."""
    project_dir: str = args["project_dir"]
    test_spec: str = args["test_spec"]
    acceptance_criteria: list[dict] = args.get("acceptance_criteria") or []
    max_retries: int = args.get("max_retries") or 3

    scope: dict = args.get("scope") or {}

    # Validate
    if not os.path.isdir(project_dir):
        return json.dumps({"error": f"project_dir does not exist: {project_dir}"})
    if not os.path.isdir(os.path.join(project_dir, ".git")):
        return json.dumps({"error": f"project_dir is not a git repo: {project_dir}"})

    # === L1: 防预污染检查 ===
    r = subprocess.run(
        ["git", "-C", project_dir, "status", "--short"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if r.stdout.strip():
        return json.dumps(
            {
                "error": f"PROJECT_DIRTY: project has uncommitted changes before pipeline_start:\n{r.stdout.strip()}"
            }
        )

    r = subprocess.run(
        ["git", "-C", project_dir, "status", "--untracked-files=all", "--short"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    untracked = [line for line in r.stdout.strip().split("\n") if line.startswith("??")]
    if untracked:
        return json.dumps(
            {
                "error": f"PROJECT_UNTRACKED: {untracked}\nOrchestrator must not create files before pipeline_start."
            }
        )
    # === 检查结束 ===

    # Phase 0 — prepare branch
    try:
        branch, ws_root = git_utils.init_branch(project_dir)
    except Exception as e:
        return json.dumps({"error": f"branch init failed: {e}"})

    task_id: str = ""
    verdict: str = "error"
    evidence_history: list[dict] = []

    evidence_archive_root = os.path.join(REAL_HOME, ".hermes", "evidence-archive")

    try:
        # Phase 0b — persist acceptance criteria for Fixer
        if acceptance_criteria:
            ac_path = os.path.join(project_dir, ".evidence", "acceptance_criteria.json")
            os.makedirs(os.path.dirname(ac_path), exist_ok=True)
            with open(ac_path, "w") as f:
                json.dump(acceptance_criteria, f, ensure_ascii=False, indent=2)
            logger.info("Wrote %s (%d criteria)", ac_path, len(acceptance_criteria))

        retry_count = 0
        nonce = secrets.token_hex(16)

        while retry_count <= max_retries:
            runner_scope = {
                "acceptance_criteria": acceptance_criteria,
                "retry_count": retry_count,
                "max_retries": max_retries,
                "baseline_passed": 0,
                "nonce": nonce,
            }
            fixer_scope = {
                "acceptance_criteria": acceptance_criteria,
                "retry_count": retry_count,
                "max_retries": max_retries,
                "allow_edit": scope.get("allow_edit") or [],
                "deny_edit": scope.get("deny_edit") or [],
                "max_diff_lines": scope.get("max_diff_lines", 50),
            }

            runner_id = _create_kanban_task(
                title=f"Run tests: {test_spec} (retry {retry_count})",
                assignee="runner",
                workspace_kind="worktree",
                workspace_path=f"{ws_root}/runner-ws-retry-{retry_count}",
                body=json.dumps(
                    {
                        "Branch": branch,
                        "Project": project_dir,
                        "Retry": retry_count,
                        "Spec": test_spec,
                        "Scope": runner_scope,
                        "Nonce": nonce,
                    },
                    ensure_ascii=False,
                ),
            )
            if not task_id:
                task_id = runner_id
            logger.info(
                "Runner task %s dispatched (retry %d/%d)",
                runner_id,
                retry_count,
                max_retries,
            )

            # --- Poll Runner ---
            try:
                evidence_data = _poll_until_done(runner_id)
            except (RuntimeError, TimeoutError, ValueError) as e:
                verdict = "error"
                return json.dumps(
                    {"error": str(e), "branch": branch},
                    ensure_ascii=False,
                )

            # --- Code-level decision: iterate acceptance criteria ---
            status, failed_gates = acceptance.evaluate_acceptance(
                evidence_data, acceptance_criteria
            )

            # 证据入栈
            evidence_history.append(evidence_data)

            if status == "pass":
                verdict = "pass"
                return json.dumps(
                    {
                        "verdict": "pass",
                        "branch": branch,
                        "evidence": evidence_data,
                        "retry_count": retry_count,
                        "failed_gates": failed_gates,
                    },
                    ensure_ascii=False,
                )

            # Failed — check retry budget
            retry_count += 1
            if retry_count > max_retries:
                verdict = "retry_exhausted"
                return json.dumps(
                    {
                        "verdict": "retry_exhausted",
                        "branch": branch,
                        "evidence": evidence_data,
                        "evidence_history": evidence_history,
                        "retry_count": retry_count - 1,
                        "failed_gates": failed_gates,
                    },
                    ensure_ascii=False,
                )

            # --- Create Fixer ---
            fixer_id = _create_kanban_task(
                title=f"Fix: {test_spec} (retry {retry_count})",
                assignee="fixer",
                workspace_kind="worktree",
                workspace_path=f"{ws_root}/fixer-ws-retry-{retry_count}",
                body=json.dumps(
                    {
                        "Branch": branch,
                        "Project": project_dir,
                        "Retry": retry_count,
                        "Spec": test_spec,
                        "Evidence": evidence_data,
                        "Scope": fixer_scope,
                    },
                    ensure_ascii=False,
                ),
            )
            logger.info(
                "Fixer task %s dispatched (retry %d/%d)",
                fixer_id,
                retry_count,
                max_retries,
            )

            # --- Poll Fixer ---
            try:
                _poll_until_done(fixer_id)
            except (RuntimeError, TimeoutError, ValueError) as e:
                verdict = "error"
                return json.dumps(
                    {"error": f"Fixer task failed: {e}", "branch": branch},
                    ensure_ascii=False,
                )

            # --- Scope hard guard ---
            violations = diff_guard.check_scope(project_dir, scope)
            if violations:
                git_utils.drop_last_commit(project_dir)
                verdict = "blocked"
                return json.dumps(
                    {
                        "verdict": "blocked",
                        "reason": violations,
                        "branch": branch,
                    },
                    ensure_ascii=False,
                )

            # --- Verifier ---
            verifier_id = _create_verifier(
                parents=[fixer_id],
                branch=branch,
                project_dir=project_dir,
                retry_count=retry_count,
                evidence=evidence_data,
                scope=fixer_scope,
                failed_gates=failed_gates,
            )
            logger.info(
                "Verifier task %s dispatched (retry %d/%d)",
                verifier_id,
                retry_count,
                max_retries,
            )
            audit = _poll_verdict(verifier_id)

            if audit.get("verdict") != "audit_pass":
                verdict = "blocked"
                return json.dumps(
                    {
                        "verdict": "blocked",
                        "reason": audit.get("block_reasons"),
                        "branch": branch,
                        "audit": audit,
                    },
                    ensure_ascii=False,
                )

            # Loop back to create new Runner

        # Unreachable — handled above, but keep as safety net
        return json.dumps({"error": "unexpected exit from pipeline loop"})

    finally:
        keep_branch = verdict in ("pass", "retry_exhausted")
        git_utils.cleanup(
            project_dir,
            branch,
            ws_root,
            task_id or "unknown",
            evidence_archive_root,
            keep_branch=keep_branch,
            verdict=verdict,
        )


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
