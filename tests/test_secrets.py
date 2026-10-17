"""Guards that keep credentials out of the repository."""

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Real Discord bot tokens are three dot-separated base64url segments.
TOKEN_PATTERN = re.compile(r"\b[A-Za-z0-9_-]{23,28}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,40}\b")

# OpenAI-style secret keys: "sk-" followed by a long run of the key alphabet.
# Deliberately anchorless-hyphen-free so placeholders like "sk-invalid…" do not match.
API_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")

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

SKIPPED_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".whl",
    ".zip",
    ".tar",
    ".gz",
    ".xlsx",
    ".xls",
    ".onnx",
}

IGNORED_SECRET_PATHS = (".env", ".env.local", "secrets/discord_token", "bot.pem", "creds.json")


def _repository_files(root: Path = REPO_ROOT):
    """Yield repository files worth scanning, pruning dependency directories."""
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames if name not in SKIPPED_DIRS and not name.endswith(".egg-info")
        )
        for filename in sorted(filenames):
            path = Path(directory) / filename
            if path.suffix not in SKIPPED_SUFFIXES:
                yield path


def _git(
    *args: str, root: Path = REPO_ROOT, stdin_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        input=stdin_text,
        capture_output=True,
        text=True,
        check=False,
    )


def _ignored_paths(root: Path, paths: list[Path]) -> set[Path]:
    """Which of ``paths`` git ignores, in one call.

    Ignored files are local state, not repository content: ``.env`` is *supposed* to hold a
    real token, and a test that refuses it would fail for every correctly configured
    developer. The rule this enforces is about what could be committed.
    """
    if not (root / ".git").exists() or not paths:
        return set()
    payload = "\n".join(str(path.relative_to(root)) for path in paths)
    result = _git("check-ignore", "--stdin", root=root, stdin_text=payload)
    if result.returncode not in (0, 1):  # 0 = some ignored, 1 = none ignored
        return set()
    return {root / line.strip() for line in result.stdout.splitlines() if line.strip()}


def _offenders(pattern: re.Pattern[str], root: Path = REPO_ROOT) -> list[str]:
    """Files that git would commit whose text matches ``pattern``."""
    files = list(_repository_files(root))
    ignored = _ignored_paths(root, files)
    found = []
    for path in files:
        if path in ignored:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if pattern.search(text):
            found.append(str(path.relative_to(root)))
    return found


def test_no_token_like_string_is_stored_in_the_repository() -> None:
    offenders = _offenders(TOKEN_PATTERN)
    assert offenders == [], f"token-like strings found in: {offenders}"


def test_no_api_key_like_string_is_stored_in_the_repository() -> None:
    offenders = _offenders(API_KEY_PATTERN)
    assert offenders == [], f"API-key-like strings found in: {offenders}"


def test_a_token_in_a_tracked_file_is_still_caught(tmp_path: Path) -> None:
    """The ignore rule must not blind the scan: only ignored files are exempt."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=False)
    (root / ".gitignore").write_text(".env\n", encoding="utf-8")
    # Two files, same secret-shaped content, one ignored and one not. The token is built
    # from parts so this test file does not itself contain a token-shaped literal.
    token = ".".join(("MTU2MTA1NDYzNzc2MTQ5OTI4Ng", "GaBcDe", "a" * 27))
    (root / ".env").write_text(f"DISCORD_TOKEN={token}\n", encoding="utf-8")
    (root / "notes.txt").write_text(f"the token is {token}\n", encoding="utf-8")

    found = _offenders(TOKEN_PATTERN, root=root)
    assert found == ["notes.txt"]


@pytest.mark.parametrize("name", IGNORED_SECRET_PATHS)
def test_secret_paths_are_git_ignored(name: str) -> None:
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git repository")
    assert _git("check-ignore", "-q", name).returncode == 0, f"{name} is not git-ignored"


def test_env_example_is_not_git_ignored() -> None:
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git repository")
    assert _git("check-ignore", "-q", ".env.example").returncode == 1
