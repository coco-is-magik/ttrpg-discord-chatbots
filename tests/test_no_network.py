"""Positive control for the network guard in conftest.py."""

import socket

import pytest


def test_the_network_guard_is_active() -> None:
    """If this passes, no other test in the suite can open a connection."""
    with pytest.raises(RuntimeError, match="must not perform network I/O"):
        socket.create_connection(("discord.com", 443), timeout=1)
