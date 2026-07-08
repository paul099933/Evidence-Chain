import os
import subprocess
from pathlib import Path

import pytest

from pipeline_core import git_utils


def _write_and_commit(repo: str, path: str, content: str):
    full = Path(repo) / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    subprocess.run(["git", "add", path], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", f"add {path}"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_init_branch_creates_branch_and_stash(temp_git_repo):
    # dirty the repo
    readme = Path(temp_git_repo) / "README.md"
    readme.write_text("dirty\n")
    branch, ws_root = git_utils.init_branch(temp_git_repo)

    assert branch.startswith("fix/pipeline-")
    assert os.path.isdir(ws_root)

    # branch exists
    result = subprocess.run(
        ["git", "branch", "--list", branch],
        cwd=temp_git_repo,
        capture_output=True,
        text=True,
    )
    assert branch in result.stdout

    # working tree is clean after stash
    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=temp_git_repo,
        capture_output=True,
        text=True,
    )
    assert status.stdout.strip() == ""

    # cleanup
    git_utils.cleanup(
        temp_git_repo,
        branch,
        ws_root,
        "task-1",
        "/tmp/evidence-archive-test",
        keep_branch=False,
        verdict="error",
    )


def test_pop_stash_restores_changes(temp_git_repo):
    readme = Path(temp_git_repo) / "README.md"
    original = readme.read_text()
    readme.write_text("dirty\n")

    branch, ws_root = git_utils.init_branch(temp_git_repo)
    git_utils.cleanup(
        temp_git_repo,
        branch,
        ws_root,
        "task-2",
        "/tmp/evidence-archive-test",
        keep_branch=False,
        verdict="error",
    )

    assert readme.read_text() == "dirty\n"


def test_remove_worktrees_cleans_directories(temp_git_repo):
    branch, ws_root = git_utils.init_branch(temp_git_repo)

    runner_ws = os.path.join(ws_root, "runner-ws-retry-0")
    os.makedirs(runner_ws, exist_ok=True)
    # fake .git file so remove_worktrees attempts cleanup
    Path(runner_ws).mkdir(parents=True, exist_ok=True)
    (Path(runner_ws) / ".git").write_text("gitdir: /tmp/fake\n")

    git_utils.remove_worktrees(ws_root)
    assert not os.path.exists(ws_root)

    git_utils.pop_stash(temp_git_repo, branch)
    git_utils._git(temp_git_repo, "branch", "-D", branch, check=False)


def test_drop_last_commit(temp_git_repo):
    _write_and_commit(temp_git_repo, "src/a.py", "v1\n")
    before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_git_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    git_utils.drop_last_commit(temp_git_repo)

    after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_git_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert after != before
    assert not (Path(temp_git_repo) / "src" / "a.py").exists()


def test_retry_exhausted_archives_logs(temp_git_repo, tmp_path):
    branch, ws_root = git_utils.init_branch(temp_git_repo)

    os.makedirs(ws_root, exist_ok=True)
    log_path = os.path.join(ws_root, "runner.log")
    Path(log_path).write_text("log content\n")

    archive_root = str(tmp_path / "archive")
    git_utils.cleanup(
        temp_git_repo,
        branch,
        ws_root,
        "task-3",
        archive_root,
        keep_branch=True,
        verdict="retry_exhausted",
    )

    archived = os.path.join(archive_root, "task-3", "runner.log")
    assert os.path.exists(archived)
    assert Path(archived).read_text() == "log content\n"

    # cleanup branch and stash
    git_utils._git(temp_git_repo, "branch", "-D", branch, check=False)
    git_utils.pop_stash(temp_git_repo, branch)
