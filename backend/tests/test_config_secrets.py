from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.config import _model_api_key


def _load_shadow_rebuild_cli():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "rebuild_shadow_index.py"
    spec = importlib.util.spec_from_file_location("shadow_rebuild_secret_test", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_production_model_key_requires_file_backed_secret(monkeypatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("ANSWER_API_KEY", "must-not-be-read-directly")
    monkeypatch.delenv("ANSWER_API_KEY_FILE", raising=False)

    with pytest.raises(ValueError, match="ANSWER_API_KEY_FILE"):
        _model_api_key("ANSWER_API_KEY")


def test_production_model_key_reads_secret_file(monkeypatch, tmp_path):
    secret_file = tmp_path / "deepseek-key"
    secret_file.write_text("file-backed-key\n", encoding="utf-8")
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("ANSWER_API_KEY", "ignored-direct-value")
    monkeypatch.setenv("ANSWER_API_KEY_FILE", str(secret_file))

    assert _model_api_key("ANSWER_API_KEY") == "file-backed-key"


def test_shadow_rebuild_cli_rejects_direct_production_secrets(monkeypatch):
    module = _load_shadow_rebuild_cli()

    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("OPENAI_API_KEY", "direct-key-must-not-be-used")
    monkeypatch.delenv("OPENAI_API_KEY_FILE", raising=False)

    with pytest.raises(ValueError, match="OPENAI_API_KEY_FILE"):
        module._secret("OPENAI_API_KEY")


@pytest.mark.parametrize("app_environment", [None, "stagin-typo"])
@pytest.mark.parametrize(
    "secret_name",
    ["OPENAI_API_KEY", "METADATA_DSN", "PGVECTOR_DSN"],
)
def test_shadow_rebuild_runtime_production_rejects_direct_secrets_when_app_env_is_bad(
    monkeypatch,
    app_environment,
    secret_name,
):
    module = _load_shadow_rebuild_cli()
    monkeypatch.setenv("RAG_RUNTIME_MODE", " PrOdUcTiOn ")
    if app_environment is None:
        monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("APP_ENVIRONMENT", app_environment)
    monkeypatch.setenv(secret_name, "direct-value-must-not-be-read")
    monkeypatch.delenv(f"{secret_name}_FILE", raising=False)

    with pytest.raises(ValueError, match=f"{secret_name}_FILE"):
        module._secret(secret_name)


@pytest.mark.parametrize(
    "secret_name",
    ["OPENAI_API_KEY", "METADATA_DSN", "PGVECTOR_DSN"],
)
def test_shadow_rebuild_runtime_production_reads_only_file_backed_secret(
    monkeypatch,
    tmp_path,
    secret_name,
):
    module = _load_shadow_rebuild_cli()
    secret_file = tmp_path / secret_name.lower()
    secret_file.write_text("file-backed-value\n", encoding="utf-8")
    monkeypatch.setenv("RAG_RUNTIME_MODE", "production")
    monkeypatch.setenv("APP_ENVIRONMENT", "misspelled")
    monkeypatch.setenv(secret_name, "direct-value-must-be-ignored")
    monkeypatch.setenv(f"{secret_name}_FILE", str(secret_file))

    assert module._secret(secret_name) == "file-backed-value"
