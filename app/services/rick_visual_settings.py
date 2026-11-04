"""Configuração Gemini visual sem alterar o LLM usado para roteiros.

A chave Gemini já pertence ao perfil próprio deste provedor. Nunca muda
app.llm_provider, as credenciais Groq ou o modelo de roteiros. Nenhuma chamada
de rede/IA é feita ao configurar a integração.
"""
from __future__ import annotations

from app.config import config

RECOMMENDED_MODELS = ("gemini-3.5-flash-lite", "gemini-3.8-flash")


def visual_gemini_snapshot() -> dict:
    settings = config.snapshot_config_with_pending(config.app)
    key = str(settings.get("gemini_api_key") or "").strip()
    model = str(settings.get("gemini_model_name") or "").strip()
    return {"key_configured": bool(key), "model": model}


def save_visual_gemini_settings(api_key: str, model: str) -> dict:
    """Persist provider-specific settings without saving or leaking the secret.

    A previously configured key may be retained by submitting an empty key.
    Return only a status label, never the credential or its checksum.
    """
    if not isinstance(api_key, str) or not isinstance(model, str):
        raise ValueError("Configuração da IA visual inválida.")
    proposed_key = api_key.strip()
    model = model.strip()
    current = visual_gemini_snapshot()
    if not proposed_key and not current["key_configured"]:
        raise ValueError("Informe a chave Gemini da IA visual.")
    # Do not accept arbitrary provider/model strings from a UI manipulation.
    if model not in RECOMMENDED_MODELS and model != current["model"]:
        raise ValueError("Modelo Gemini visual não permitido.")
    if not model or len(proposed_key) > 200:
        raise ValueError("Configuração da IA visual inválida.")

    changes = {"gemini_model_name": model}
    if proposed_key:
        changes["gemini_api_key"] = proposed_key
    applied = config.update_config_values_nonblocking(config.app, changes)
    saved = config.try_save_config()
    return {
        "status": "saved" if saved else "queued_for_save",
        "applied": bool(applied),
        "model": model,
    }
