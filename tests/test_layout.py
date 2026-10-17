"""The project must live in one directory, and its environment must agree.

This exists because it went wrong once, in a way that is invisible until something
mysterious fails: the virtualenv had been copied from a previous checkout, so its
``pip`` wrapper, ``activate`` script and every console script still pointed at the *old*
directory. Installs appeared to work and landed somewhere else. Worse, the shell had that
old environment active, so a bare ``python3`` was the wrong interpreter.

The tests below turn that class of mistake into a loud failure at import time.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import ttrpg_chatbots

ROOT = Path(__file__).resolve().parent.parent

# What actually went wrong: this checkout's neighbour, "../ttrpg-chatbots", was baked into
# the virtualenv. Match that sibling specifically, by full path, so ordinary names like
# "ttrpg-chatbots-dice" (a console script) and "~/.cache/ttrpg-chatbots" (a cache) are not
# mistaken for it. "-rebuild" after the name means this checkout.
SIBLING = re.compile(
    re.escape(str(ROOT.parent)) + r"/ttrpg-chatbots(?![-A-Za-z0-9])"
)


def _foreign_references(path: Path) -> list[str]:
    """Lines in ``path`` naming the sibling checkout rather than this one."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    if "ttrpg-chatbots" not in text:
        return []
    return [line.strip() for line in text.splitlines() if SIBLING.search(line)]


def test_the_package_under_test_is_this_checkout() -> None:
    package = Path(ttrpg_chatbots.__file__).resolve()
    assert package.is_relative_to(ROOT), f"imported {package}, expected a file under {ROOT}"
    assert package.parent == ROOT / "src" / "ttrpg_chatbots"


def test_the_interpreter_belongs_to_this_checkout() -> None:
    """A bare ``python3`` from a stale activated venv is the original failure mode."""
    if Path(sys.prefix).name != ".venv":
        pytest.skip("not running inside a project venv")
    assert Path(sys.prefix).resolve().is_relative_to(ROOT), (
        f"running in {sys.prefix}, which is not this checkout's venv"
    )


def test_pyvenv_cfg_names_this_checkout() -> None:
    config = ROOT / ".venv" / "pyvenv.cfg"
    if not config.is_file():
        pytest.skip("no venv in this checkout")
    offenders = _foreign_references(config)
    assert offenders == [], f"pyvenv.cfg points elsewhere: {offenders}"


def test_the_activation_scripts_name_this_checkout() -> None:
    scripts = [ROOT / ".venv" / "bin" / name for name in ("activate", "activate.fish")]
    scripts.append(ROOT / ".venv" / "scripts" / "Activate.ps1")
    checked = 0
    for script in scripts:
        if not script.is_file():
            continue
        checked += 1
        offenders = _foreign_references(script)
        assert offenders == [], f"{script.name} points elsewhere: {offenders}"
    if not checked:
        pytest.skip("no activation scripts")


def test_every_console_script_uses_this_checkouts_python() -> None:
    """The console scripts' shebangs, and the ``pip`` wrapper, must be local."""
    bin_dir = ROOT / ".venv" / "bin"
    if not bin_dir.is_dir():
        pytest.skip("no venv in this checkout")
    script = bin_dir / "ttrpg-chatbots"
    if not script.is_file():
        pytest.skip("the project is not installed in this venv")
    checked = [bin_dir / name for name in ("pip", "pip3", "ttrpg-chatbots")]
    checked += sorted(bin_dir.glob("ttrpg-chatbots-*"))
    for path in checked:
        if not path.is_file():
            continue
        people = _foreign_references(path)
        assert people == [], f"{path.name} points elsewhere: {people}"
        text = path.read_text(encoding="utf-8", errors="ignore").splitlines()[0:3]
        assert any(str(ROOT) in line for line in text), (
            f"{path.name} does not invoke {ROOT}/.venv"
        )


def test_the_installed_metadata_names_this_checkout() -> None:
    """``pip show`` should describe this directory, not a git checkout of it."""
    result = subprocess.run(
        [sys.executable, "-m", "pip", "show", "ttrpg-chatbots"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("the project is not installed")
    assert str(ROOT) in result.stdout, result.stdout


SCANNED_SUFFIXES = {
    ".py",
    ".md",
    ".toml",
    ".cfg",
    ".ini",
    ".example",
    ".env",
    ".sh",
    ".service",
    ".yml",
    ".yaml",
}
SCANNED_NAMES = {".gitignore", "Makefile", "Dockerfile"}


def test_no_tracked_file_names_another_checkout() -> None:
    """Source, docs, scripts and tests must not hard-code a sibling directory."""
    offenders = []
    for directory, dirnames, filenames in os.walk(ROOT):
        # Prune rather than filter: walking .venv costs tens of thousands of files.
        dirnames[:] = sorted(
            name for name in dirnames if name not in {".git", ".venv", "__pycache__", "data"}
        )
        for filename in sorted(filenames):
            path = Path(directory) / filename
            if path.suffix not in SCANNED_SUFFIXES and path.name not in SCANNED_NAMES:
                continue
            found = _foreign_references(path)
            if found:
                offenders.append(f"{path.relative_to(ROOT)}: {found[0]}")
    assert offenders == [], "files name another checkout:\n" + "\n".join(offenders)
