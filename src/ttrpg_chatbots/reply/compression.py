"""Compressors used as the distance metric.

NCD only ever needs the *length* of a compressed stream, never its bytes, so every
compressor exposes ``compressed_length``. gzip/zlib/bz2/lzma ship with Python, so
the core engine has no dependencies; zstd is optional (``.[reply]``) and worth it
once a corpus gets large.

Lengths are not cached here: the classifier measures the corpus once when it
prepares items, which is the only place a cache pays for itself.
"""

from __future__ import annotations

import bz2
import gzip
import lzma
import zlib
from importlib.util import find_spec
from typing import Protocol, runtime_checkable

from ttrpg_chatbots.reply.types import ReplyError

DEFAULT = "deflate"
LEVEL = 9


@runtime_checkable
class Compressor(Protocol):
    """Turns bytes into a compressed byte count."""

    name: str

    def compressed_length(self, data: bytes) -> int:
        """Return the compressed size of ``data`` in bytes."""


class DeflateCompressor:
    """Raw DEFLATE with no container header -- the default.

    gzip and zlib prepend 18 or 6 constant bytes, which is a large fraction of a
    short question and flattens the distance scale. Measured on the demo world
    this ranks 13/14 test questions correctly, against 12/14 for gzip.
    """

    name = "deflate"

    def compressed_length(self, data: bytes) -> int:
        engine = zlib.compressobj(LEVEL, zlib.DEFLATED, -15)
        return len(engine.compress(data) + engine.flush())


class GzipCompressor:
    """The method's reference compressor; header-heavy on short text."""

    name = "gzip"

    def compressed_length(self, data: bytes) -> int:
        return len(gzip.compress(data, compresslevel=LEVEL, mtime=0))


class ZlibCompressor:
    """Deflate wrapped in zlib framing (6 bytes of header/trailer)."""

    name = "zlib"

    def compressed_length(self, data: bytes) -> int:
        return len(zlib.compress(data, LEVEL))


class Bz2Compressor:
    """Better ratio than deflate on repetitive prose, noticeably slower."""

    name = "bz2"

    def compressed_length(self, data: bytes) -> int:
        return len(bz2.compress(data, LEVEL))


class LzmaCompressor:
    """Best ratio here and the slowest; fine for a small static corpus."""

    name = "lzma"

    def compressed_length(self, data: bytes) -> int:
        return len(lzma.compress(data, preset=LEVEL))


class ZstdCompressor:
    """Optional: requires the ``zstandard`` package (``.[reply]`` extra)."""

    name = "zstd"

    def __init__(self) -> None:
        try:
            import zstandard
        except ImportError as error:  # pragma: no cover - covered by the skip test
            raise ReplyError(
                "the zstd compressor needs 'zstandard': pip install -e '.[reply]'"
            ) from error
        self._compressor = zstandard.ZstdCompressor(level=19)

    def compressed_length(self, data: bytes) -> int:
        return len(self._compressor.compress(data))


_FACTORIES = {
    "deflate": DeflateCompressor,
    "gzip": GzipCompressor,
    "zlib": ZlibCompressor,
    "bz2": Bz2Compressor,
    "lzma": LzmaCompressor,
    "zstd": ZstdCompressor,
}


def names() -> tuple[str, ...]:
    return tuple(_FACTORIES)


def is_available(name: str) -> bool:
    if name == "zstd":
        return find_spec("zstandard") is not None
    return name in _FACTORIES


def available() -> tuple[str, ...]:
    return tuple(name for name in _FACTORIES if is_available(name))


def get(name: str) -> Compressor:
    factory = _FACTORIES.get(name.strip().lower())
    if factory is None:
        raise ReplyError(f"unknown compressor {name!r}; available: {', '.join(available())}")
    return factory()
