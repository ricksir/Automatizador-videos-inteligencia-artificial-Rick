"""Visual Gemini configuration never replaces the current Groq script LLM."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import rick_visual_settings as settings


@pytest.fixture
def configured(monkeypatch):
    store = {
        "llm_provider": "groq",
        "groq_api_key": "old-groq-secret",
        "groq_model_name": "openai/gpt-oss-120b",
        "gemini_api_key": "",
        "gemini_model_name": "",
    }
    writes = []
    saves = []
    monkeypatch.setattr(settings.config, "app", store)
    monkeypatch.setattr(
        settings.config, "snapshot_config_with_pending",
        lambda section: dict(section),
    )
    def update(section, values):
        writes.append(dict(values))
        section.update(values)
        return True
    monkeypatch.setattr(
        settings.config, "update_config_values_nonblocking", update,
    )
    monkeypatch.setattr(
        settings.config, "try_save_config",
        lambda: saves.append(True) or True,
    )
    return store, writes, saves


def test_visual_key_saved_without_changing_groq(configured):
    store, writes, saves = configured
    result = settings.save_visual_gemini_settings(
        "gemini-secret", "gemini-3.5-flash-lite",
    )
    assert result == {
        "status": "saved", "applied": True,
        "model": "gemini-3.5-flash-lite",
    }
    assert "gemini-secret" not in str(result)
    assert store["gemini_api_key"] == "gemini-secret"
    assert store["gemini_model_name"] == "gemini-3.5-flash-lite"
    assert store["llm_provider"] == "groq"
    assert store["groq_api_key"] == "old-groq-secret"
    assert store["groq_model_name"] == "openai/gpt-oss-120b"
    assert len(writes) == 1
    assert len(saves) == 1
    assert set(writes[0]) == {"gemini_api_key", "gemini_model_name"}


def test_existing_key_can_be_reused_without_reentering_secret(configured):
    store, writes, _ = configured
    store["gemini_api_key"] = "existing-key"
    result = settings.save_visual_gemini_settings(
        "", "gemini-3.8-flash",
    )
    assert result["status"] == "saved"
    assert store["gemini_api_key"] == "existing-key"
    assert writes == [{"gemini_model_name": "gemini-3.8-flash"}]


def test_missing_key_rejected_without_any_writes(configured):
    _, writes, saves = configured
    with pytest.raises(ValueError, match="chave Gemini"):
        settings.save_visual_gemini_settings(
            "", "gemini-3.5-flash-lite",
        )
    assert writes == []
    assert saves == []


def test_arbitrary_model_not_accepted(configured):
    _, writes, _ = configured
    with pytest.raises(ValueError, match="Modelo Gemini"):
        settings.save_visual_gemini_settings(
            "valid-key", "gemini-run-unexpected",
        )
    assert writes == []


def test_existing_custom_model_can_be_retained(configured):
    store, writes, _ = configured
    store["gemini_api_key"] = "old"
    store["gemini_model_name"] = "existing-custom-multimodal"
    settings.save_visual_gemini_settings(
        "", "existing-custom-multimodal",
    )
    assert writes == [{"gemini_model_name": "existing-custom-multimodal"}]


def test_deferred_save_does_not_claim_persistence(configured, monkeypatch):
    store, _, _ = configured
    monkeypatch.setattr(settings.config, "try_save_config", lambda: False)
    status = settings.save_visual_gemini_settings(
        "new-key", "gemini-3.8-flash",
    )
    assert status["status"] == "queued_for_save"
    assert store["llm_provider"] == "groq"


def test_key_never_returned_through_snapshot(configured):
    store, _, _ = configured
    store["gemini_api_key"] = "private-token"
    store["gemini_model_name"] = "gemini-3.5-flash-lite"
    snapshot = settings.visual_gemini_snapshot()
    assert snapshot == {
        "key_configured": True,
        "model": "gemini-3.5-flash-lite",
    }
    assert "private-token" not in repr(snapshot)


def test_ui_does_not_require_switching_groq_provider():
    code = (
        Path(__file__).parents[2] / "webui" / "rick_editorial_panel.py"
    ).read_text(encoding="utf-8")
    assert "Configurar IA visual — sem alterar o provedor de roteiros" in code
    assert "Salvar configuração da IA visual" in code
    assert "save_visual_gemini_settings" in code
    assert 'type="password"' in code
    assert "Autorizo o envio externo" in code
    assert "disabled=not (authorized and key_ready and model_name)" in code
    assert "config.app, \"llm_provider\"" not in code
