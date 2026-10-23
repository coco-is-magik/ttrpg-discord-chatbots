"""Suite-wide safety rails.

Tests must never reach Discord: there are no credentials in the suite, and API
traffic from a test run would breach Discord's rate limits. Socket connections
are refused for every test, so a test that silently starts relying on the network
fails here instead of somewhere less obvious.
"""

import socket

import pytest


class NetworkAccessBlocked(RuntimeError):
    """Raised when a test tries to open a network connection."""


def _refuse(*args, **kwargs):
    raise NetworkAccessBlocked("tests must not perform network I/O; fake the boundary instead")


@pytest.fixture(autouse=True)
def isolate_memory(tmp_path, monkeypatch):
    """Point every friend's memory at a throwaway database.

    Memory is written by answering a message, and a test that answers a message must not write the
    real `data/memory.db` -- which it did, once, through `build_entries` migrating at startup.
    """
    monkeypatch.setenv("TTRPG_FRIENDS_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("TTRPG_MEMORY_DB", str(tmp_path / "memory" / "memory.db"))


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Refuse outbound connections for every test."""
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


@pytest.fixture(autouse=True)
def a_fixed_hour(monkeypatch):
    """Run every test at 14:00 on a fixed day.

    Found the hard way: at 23:05 the suite reported 16 failures, all of them ladder tests, because
    Terry's schedule says he is asleep and `decide/floor` therefore abstains. Nothing was wrong with
    the code -- the tests were reading the wall clock, so they passed all afternoon and failed at
    night. A test that depends on when it is run is not a test.

    Tests that *are* about time pass an explicit moment or day and are unaffected.
    """
    from datetime import datetime

    from ttrpg_chatbots.perceive.clock import read_clock as real_read_clock

    fixed = real_read_clock(datetime(2026, 10, 22, 14, 0))
    monkeypatch.setattr(
        "ttrpg_chatbots.bots.ladder.read_clock", lambda *args, **kwargs: fixed, raising=False
    )
