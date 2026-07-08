from __future__ import annotations

import fnmatch
import re
import subprocess


class DiffGuardError(Exception):
    """Raised when a scope violation is detected."""

    def __init__(self, violations: list[str]):
        self.violations = violations
        super().__init__("\n".join(violations))


def _git(project_dir: str, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", project_dir] + list(args),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return r.stdout.strip()


def _parse_diff_stat(stat: str) -> int:
    """Parse 'git diff --stat' output and return total changed lines."""
    total = 0
    for line in stat.splitlines():
        parts = line.split("|")
        if len(parts) != 2:
            continue
        count_part = parts[1].strip()
        match = re.search(r"(\d+)\s*[+-]", count_part)
        if match:
            total += int(match.group(1))
    return total


def check_scope(
    project_dir: str,
    scope: dict,
    *,
    base_ref: str = "HEAD~1",
    head_ref: str = "HEAD",
) -> list[str]:
    """Check Fixer diff against scope constraints.

    Empty allow_edit means "no explicit allowlist" -> allow all (unless denied).
    Explicit allow_edit=[] means deny all.

    Returns list of violation messages. Empty means OK.
    """
    violations: list[str] = []

    allow_edit = scope.get("allow_edit")
    deny_edit = scope.get("deny_edit") or []
    max_lines = scope.get("max_diff_lines", 50)

    diff_files = _git(project_dir, "diff", "--name-only", base_ref, head_ref).splitlines()
    diff_stat = _git(project_dir, "diff", "--stat", base_ref, head_ref)

    for f in diff_files:
        if not f:
            continue
        for pat in deny_edit:
            if fnmatch.fnmatch(f, pat):
                violations.append(f"deny_edit violation: {f} matches {pat}")

        # allow_edit=None means "no restriction"; allow_edit=[] means "deny all".
        if allow_edit is not None:
            allowed = any(fnmatch.fnmatch(f, pat) for pat in allow_edit)
            if not allowed:
                violations.append(f"allow_edit violation: {f} not in {allow_edit}")

    changed_lines = _parse_diff_stat(diff_stat)
    if changed_lines > max_lines:
        violations.append(f"max_diff_lines exceeded: {changed_lines} > {max_lines}")

    return violations
