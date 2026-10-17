import pytest

from ttrpg_chatbots.stt import engines
from ttrpg_chatbots.stt.engines import EngineSpec
from ttrpg_chatbots.stt.recognizer import EngineUnavailable


def _spec(module: str = "json", ready: bool = True, detail: str = "ready") -> EngineSpec:
    return EngineSpec(
        name="fake",
        distribution="fake-dist",
        module=module,
        summary="fake engine",
        check=lambda: (ready, detail),
        build=lambda: None,
    )


def test_registry_declares_the_expected_engines() -> None:
    """Availability checks must not import the engines, or a missing model breaks startup."""
    assert engines.names() == ("vosk", "faster-whisper", "sherpa-onnx")


def test_missing_package_is_reported_as_unavailable() -> None:
    status = engines.availability(_spec(module="definitely_not_a_real_module_xyz"))
    assert status.available is False
    assert "fake-dist" in status.detail
    assert "not installed" in status.detail


def test_the_engine_check_result_is_passed_through() -> None:
    status = engines.availability(_spec(ready=False, detail="no model here"))
    assert (status.available, status.detail) == (False, "no model here")


def test_a_broken_check_cannot_escape_and_kill_startup() -> None:
    broken = EngineSpec("fake", "fake-dist", "json", "summary", lambda: 1 / 0, lambda: None)
    status = engines.availability(broken)
    assert status.available is False
    assert "availability check failed" in status.detail


def test_unknown_engine_build_raises_with_the_choices() -> None:
    with pytest.raises(EngineUnavailable, match="vosk"):
        engines.build_engine("nope")


def test_model_dir_honours_the_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TTRPG_STT_MODEL_DIR", str(tmp_path / "models"))
    assert engines.model_dir() == tmp_path / "models"
    assert (tmp_path / "models").is_dir()


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_offline_flag_is_recognised(monkeypatch, value) -> None:
    monkeypatch.setenv("TTRPG_STT_OFFLINE", value)
    assert engines.offline() is True


def test_offline_defaults_to_false(monkeypatch) -> None:
    monkeypatch.delenv("TTRPG_STT_OFFLINE", raising=False)
    assert engines.offline() is False
