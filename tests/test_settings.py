import os
from pathlib import Path

import pytest

from cloop.settings import (
    EmbedStorageMode,
    ToolMode,
    VectorSearchMode,
    get_settings,
)


def test_settings_use_enums(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOOP_DATA_DIR", os.getcwd())
    get_settings.cache_clear()
    settings = get_settings()
    assert isinstance(settings.vector_search_mode, VectorSearchMode)
    assert isinstance(settings.tool_mode_default, ToolMode)
    assert isinstance(settings.embed_storage_mode, EmbedStorageMode)


@pytest.mark.parametrize(
    ("env_var", "value"),
    [
        ("CLOOP_VECTOR_MODE", "unsupported"),
        ("CLOOP_TOOL_MODE", "bogus"),
        ("CLOOP_EMBED_STORAGE", "invalid"),
    ],
)
def test_invalid_enum_values_raise(
    monkeypatch: pytest.MonkeyPatch, env_var: str, value: str
) -> None:
    monkeypatch.setenv("CLOOP_DATA_DIR", os.getcwd())
    monkeypatch.setenv(env_var, value)
    get_settings.cache_clear()
    with pytest.raises(ValueError):
        get_settings()


def test_sqlite_requires_json_or_dual(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOOP_DATA_DIR", os.getcwd())
    monkeypatch.setenv("CLOOP_VECTOR_MODE", "sqlite")
    monkeypatch.setenv("CLOOP_EMBED_STORAGE", "blob")
    get_settings.cache_clear()
    with pytest.raises(ValueError):
        get_settings()


def test_stream_default_disallowed_with_llm_tool_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOOP_DATA_DIR", os.getcwd())
    monkeypatch.setenv("CLOOP_TOOL_MODE", "llm")
    monkeypatch.setenv("CLOOP_STREAM_DEFAULT", "true")
    get_settings.cache_clear()
    with pytest.raises(ValueError):
        get_settings()


def test_defaults_disable_background_automation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Autopilot and scheduler should default to disabled for safe first-run behavior."""
    import cloop.settings as settings_module

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("CLOOP_AUTOPILOT_ENABLED", raising=False)
    monkeypatch.delenv("CLOOP_SCHEDULER_ENABLED", raising=False)

    monkeypatch.setattr(settings_module, "_DOTENV_LOADED", False)
    settings_module.get_settings.cache_clear()

    settings = settings_module.get_settings()
    assert settings.autopilot_enabled is False
    assert settings.scheduler_enabled is False


def test_negative_priority_weight_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative priority weights should raise ValueError."""
    import cloop.settings as settings_module

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_PRIORITY_WEIGHT_DUE", "-1.0")
    monkeypatch.setattr(settings_module, "_DOTENV_LOADED", False)
    settings_module.get_settings.cache_clear()

    with pytest.raises(ValueError, match="PRIORITY_WEIGHT_DUE must be non-negative"):
        settings_module.get_settings()
