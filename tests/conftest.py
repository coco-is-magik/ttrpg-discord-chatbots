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
def block_network(monkeypatch):
    """Refuse outbound connections for every test."""
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
