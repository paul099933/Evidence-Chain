from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

REAL_HOME = "/home/agent"


class GitError(RuntimeError):
    pass


def _git(project_dir: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(
        ["git", "-C", project_dir] + list(args),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if check and r.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r


def init_branch(project_dir: str) -> tuple[str, str]:
    """Stash uncommitted changes and create a fix branch.

    Returns (branch_name, ws_root).
    """
    branch = f"fix/pipeline-{int(time.time())}"
    ws_root = f"/tmp/evidence-chain/{branch}"

    _git(
        project_dir,
        "stash",
        "push",
        "--include-untracked",
        "-m",
        f"evidence-chain-clean-{branch}",
    )
    _git(project_dir, "branch", branch, "HEAD")
    Path(ws_root).mkdir(parents=True, exist_ok=True)

    logger.info("Created branch=%s ws_root=%s", branch, ws_root)
    return branch, ws_root


def pop_stash(project_dir: str, branch: str) -> bool:
    """Pop the stash created for this branch, if it exists."""
    stash_msg = f"evidence-chain-clean-{branch}"
    r = _git(project_dir, "stash", "list", check=False)
    for line in r.stdout.splitlines():
        if stash_msg in line:
            stash_ref = line.split(":")[0]
            _git(project_dir, "stash", "pop", stash_ref)
            logger.info("Popped stash %s", stash_ref)
            return True
    return False


def remove_worktrees(ws_root: str) -> None:
    """Remove runner/fixer worktree directories under ws_root."""
    if not os.path.isdir(ws_root):
        return
    for entry in os.listdir(ws_root):
        if not entry.startswith(("runner-ws-", "fixer-ws-")):
            continue
        wt_path = os.path.join(ws_root, entry)
        git_dir = os.path.join(wt_path, ".git")
        if os.path.exists(git_dir):
            try:
                subprocess.run(
                    ["git", "-C", wt_path, "worktree", "remove", "--force", wt_path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except Exception as e:
                logger.warning("worktree remove failed for %s: %s", wt_path, e)
    shutil.rmtree(ws_root, ignore_errors=True)
    logger.info("Removed worktree root %s", ws_root)


def archive_logs(task_id: str, ws_root: str, evidence_root: str) -> None:
    """Copy *.log from ws_root to evidence archive."""
    log_dir = os.path.join(evidence_root, task_id)
    os.makedirs(log_dir, exist_ok=True)
    if not os.path.isdir(ws_root):
        return
    for entry in os.listdir(ws_root):
        if entry.endswith(".log"):
            src = os.path.join(ws_root, entry)
            dst = os.path.join(log_dir, entry)
            shutil.copy2(src, dst)
            logger.info("Archived log %s -> %s", src, dst)


def drop_last_commit(project_dir: str) -> None:
    """Drop the most recent commit (e.g. a Fixer commit that violated scope)."""
    _git(project_dir, "reset", "--hard", "HEAD~1")
    logger.info("Dropped last commit in %s", project_dir)


def cleanup(
    project_dir: str,
    branch: str,
    ws_root: str,
    task_id: str,
    evidence_root: str,
    *,
    keep_branch: bool = False,
    verdict: str = "",
) -> None:
    """Idempotent cleanup."""
    try:
        if verdict == "retry_exhausted":
            archive_logs(task_id, ws_root, evidence_root)
        remove_worktrees(ws_root)
        if not keep_branch:
            _git(project_dir, "branch", "-D", branch, check=False)
        pop_stash(project_dir, branch)
    except Exception:
        logger.exception("cleanup failed for branch=%s task=%s", branch, task_id)
        raise
