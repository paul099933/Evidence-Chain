import os
import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_git_repo():
    """Yield a temporary git repository with an initial commit."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["git", "init"], cwd=tmp, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=tmp,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=tmp,
            check=True,
            capture_output=True,
        )
        readme = Path(tmp) / "README.md"
        readme.write_text("init\n")
        subprocess.run(["git", "add", "."], cwd=tmp, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp,
            check=True,
            capture_output=True,
        )
        yield tmp


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp
