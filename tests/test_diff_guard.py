import os
from pathlib import Path

from pipeline_core.diff_guard import check_scope


def _commit_file(repo: str, path: str, content: str):
    full = Path(repo) / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    import subprocess

    subprocess.run(["git", "add", path], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", f"add {path}"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _amend_with_change(repo: str, path: str, content: str):
    full = Path(repo) / path
    full.write_text(content)
    import subprocess

    subprocess.run(["git", "add", path], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", f"update {path}"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_no_scope_allows_all(temp_git_repo):
    _commit_file(temp_git_repo, "src/a.py", "print(1)\n")
    _amend_with_change(temp_git_repo, "src/a.py", "print(2)\n")
    assert check_scope(temp_git_repo, {}) == []


def test_deny_edit_hit(temp_git_repo):
    _commit_file(temp_git_repo, "src/a.py", "print(1)\n")
    _amend_with_change(temp_git_repo, "src/a.py", "print(2)\n")
    violations = check_scope(temp_git_repo, {"deny_edit": ["src/*.py"]})
    assert any("deny_edit violation" in v for v in violations)


def test_allow_edit_restricts(temp_git_repo):
    _commit_file(temp_git_repo, "src/a.py", "print(1)\n")
    _commit_file(temp_git_repo, "README.md", "docs\n")
    _amend_with_change(temp_git_repo, "README.md", "updated docs\n")
    violations = check_scope(temp_git_repo, {"allow_edit": ["src/*"]})
    assert any("allow_edit violation" in v for v in violations)


def test_allow_edit_empty_denies_all(temp_git_repo):
    _commit_file(temp_git_repo, "src/a.py", "print(1)\n")
    _amend_with_change(temp_git_repo, "src/a.py", "print(2)\n")
    violations = check_scope(temp_git_repo, {"allow_edit": []})
    assert any("allow_edit violation" in v for v in violations)


def test_max_diff_lines(temp_git_repo):
    _commit_file(temp_git_repo, "src/a.py", "line1\nline2\nline3\n")
    _amend_with_change(
        temp_git_repo,
        "src/a.py",
        "line1\nline2\nline3\nline4\nline5\nline6\n",
    )
    violations = check_scope(temp_git_repo, {"max_diff_lines": 2})
    assert any("max_diff_lines exceeded" in v for v in violations)


def test_legal_diff_passes(temp_git_repo):
    _commit_file(temp_git_repo, "src/a.py", "print(1)\n")
    _amend_with_change(temp_git_repo, "src/a.py", "print(2)\n")
    violations = check_scope(
        temp_git_repo,
        {"allow_edit": ["src/*"], "deny_edit": ["*.md"], "max_diff_lines": 50},
    )
    assert violations == []
