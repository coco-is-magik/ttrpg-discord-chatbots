"""Guards that keep credentials out of the repository."""

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Real Discord bot tokens are three dot-separated base64url segments.
TOKEN_PATTERN = re.compile(r"\b[A-Za-z0-9_-]{23,28}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,40}\b")

SKIPPED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "build",
    "dist",
}

SKIPPED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".whl", ".zip", ".tar", ".gz"}

IGNORED_SECRET_PATHS = (".env", ".env.local", "secrets/discord_token", "bot.pem", "creds.json")


def _repository_files():
    """Yield repository files worth scanning, pruning dependency directories."""
    for directory, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = sorted(
            name for name in dirnames if name not in SKIPPED_DIRS and not name.endswith(".egg-info")
        )
        for filename in sorted(filenames):
            path = Path(directory) / filename
            if path.suffix not in SKIPPED_SUFFIXES:
                yield path


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, check=False
    )


def test_no_token_like_string_is_stored_in_the_repository() -> None:
    offenders = []
    for path in _repository_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if TOKEN_PATTERN.search(text):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], f"token-like strings found in: {offenders}"


@pytest.mark.parametrize("name", IGNORED_SECRET_PATHS)
def test_secret_paths_are_git_ignored(name: str) -> None:
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git repository")
    assert _git("check-ignore", "-q", name).returncode == 0, f"{name} is not git-ignored"


def test_env_example_is_not_git_ignored() -> None:
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git repository")
    assert _git("check-ignore", "-q", ".env.example").returncode == 1
