import pytest

from ttrpg_chatbots.reply import compression
from ttrpg_chatbots.reply.types import ReplyError

REPETITIVE = b"the tide turns at the quay " * 40
PLAIN = b"zq"


@pytest.mark.parametrize("name", ["deflate", "gzip", "zlib", "bz2", "lzma"])
def test_every_stdlib_compressor_measures_a_length(name: str) -> None:
    compressor = compression.get(name)
    assert compressor.compressed_length(REPETITIVE) > 0
    assert compressor.compressed_length(PLAIN) > 0


def test_deflate_is_the_default_and_has_no_framing() -> None:
    assert compression.DEFAULT == "deflate"
    assert compression.names()[0] == "deflate"
    assert compression.get(compression.DEFAULT).name == "deflate"


def test_framing_costs_show_up_as_length() -> None:
    """The rationale for headerless deflate: gzip must be measurably bigger."""
    deflate = compression.get("deflate").compressed_length(PLAIN)
    gzip_length = compression.get("gzip").compressed_length(PLAIN)
    assert gzip_length > deflate


def test_lengths_are_deterministic() -> None:
    compressor = compression.get("deflate")
    assert compressor.compressed_length(REPETITIVE) == compressor.compressed_length(REPETITIVE)


def test_compression_actually_compresses() -> None:
    assert compression.get("deflate").compressed_length(REPETITIVE) < len(REPETITIVE)


def test_lookup_is_case_insensitive() -> None:
    assert compression.get("GZIP").name == "gzip"


def test_unknown_compressor_lists_the_choices() -> None:
    with pytest.raises(ReplyError, match="deflate"):
        compression.get("brotli")


def test_compressors_satisfy_the_protocol() -> None:
    assert isinstance(compression.get("deflate"), compression.Compressor)


@pytest.mark.skipif(
    not compression.is_available("zstd"), reason="zstandard is an optional extra"
)
def test_zstd_is_available_when_installed() -> None:
    assert "zstd" in compression.available()
    assert compression.get("zstd").compressed_length(REPETITIVE) > 0


def test_zstd_is_hidden_when_the_package_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(compression, "find_spec", lambda name: None)
    assert "zstd" not in compression.available()
