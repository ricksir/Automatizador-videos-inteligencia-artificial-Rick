"""Conservative semantic review when narration splits negation over scenes.

All Google calls are fake. No external requests, publishing, approvals,
downloads, writes to task storage, or use of personal credentials.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from app.services import rick_semantic_frame_review as review


def _response(verdict, relation):
    return {
        "verdict": verdict,
        "visual_relation": relation,
        "visible_evidence": "Chamas e madeira queimando em uma lareira.",
        "reason": "O fogo evoca apenas uma metáfora de revolução.",
    }


def test_conservative_gate_rejects_metaphor_even_if_model_says_plausible():
    result = review._parse_assessment(
        json.dumps(_response("plausible", "metaphorical"))
    )
    assert result["verdict"] == "uncertain"
    assert result["visual_relation"] == "metaphorical"
    assert result["requires_strict_review"] is True
    assert result["recommended_action"] == "buscar_alternativa"


@pytest.mark.parametrize("relation", [
    "contextual", "insufficient", "unrelated",
])
def test_nonliteral_relation_never_means_plausible(relation):
    result = review._parse_assessment(
        json.dumps(_response("plausible", relation))
    )
    assert result["verdict"] == "uncertain"
    assert result["requires_strict_review"] is True


def test_direct_visible_correspondence_is_still_only_plausible():
    result = review._parse_assessment(
        json.dumps({
            "verdict": "plausible",
            "visual_relation": "direct",
            "visible_evidence": "Várias pessoas depositam cédulas nas urnas.",
            "reason": "A cena narra uma eleição e há votação visível.",
        })
    )
    assert result["verdict"] == "plausible"
    assert result["recommended_action"] == "revisar_conteudo_e_direitos"
    assert result["requires_strict_review"] is False


def test_old_response_without_visual_relation_is_not_promoted():
    result = review._parse_assessment(
        json.dumps({
            "verdict": "plausible",
            "visible_evidence": "Um fogo",
            "reason": "Lembra uma revolução",
        })
    )
    assert result["verdict"] == "uncertain"
    assert result["visual_relation"] == "insufficient"


def test_unrecognized_relation_fails_closed():
    with pytest.raises(ValueError, match="invalid_model_response"):
        review._parse_assessment(json.dumps(_response(
            "plausible", "guaranteed_historical_match",
        )))


def test_context_includes_sem_from_previous_scene():
    scenes = [
        {"scene_number": 1, "text": "Gramsci estudou como ideias dominam"},
        {"scene_number": 2, "text": "a sociedade e como"},
        {"scene_number": 3, "text": "grupos podem mudar isso sem"},
        {"scene_number": 4, "text": "precisar de revoluções violentas."},
    ]
    context = review._narration_context(scenes, 4)
    assert "Cena 3: grupos podem mudar isso sem" in context
    assert "Cena 4: precisar de revoluções violentas." in context
    assert context.index("isso sem") < context.index("precisar de")


def test_long_context_is_bounded():
    scenes = [
        {"scene_number": index, "text": "conceito " * 100}
        for index in range(1, 25)
    ]
    assert len(review._narration_context(scenes, 12)) <= 700


def test_contextual_remote_prompt_and_output_without_autoapproval(
    tmp_path, monkeypatch,
):
    observed = []

    class Client:
        def __init__(self, *, api_key):
            assert api_key == "fake-secret"
            self.models = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def generate_content(self, *, model, contents, config):
            observed.append((model, contents, config))
            return types.SimpleNamespace(
                text=json.dumps(_response("plausible", "metaphorical"))
            )

    class Part:
        @classmethod
        def from_bytes(cls, *, data, mime_type):
            assert data == b"local-jpeg"
            assert mime_type == "image/jpeg"
            return (mime_type, data)

    google = types.ModuleType("google")
    genai = types.ModuleType("google.genai")
    genai.Client = Client
    genai.types = types.SimpleNamespace(
        Part=Part,
        GenerateContentConfig=lambda **kwargs: kwargs,
    )
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setattr(
        review, "_color_frame", lambda path, second: b"local-jpeg",
    )
    path = tmp_path / "movie.mp4"
    path.write_bytes(b"file mocked for testing")
    scenes = [
        {"scene_number": 1, "text": "Gramsci estudou como ideias dominam",
         "primary": "movie.mp4"},
        {"scene_number": 2, "text": "a sociedade e como",
         "primary": "movie.mp4"},
        {"scene_number": 3, "text": "grupos podem mudar isso sem",
         "primary": "movie.mp4"},
        {"scene_number": 4, "text": "precisar de revoluções violentas.",
         "primary": "movie.mp4"},
    ]
    report = review.review_scene_frames(
        {"scenes": scenes}, {"movie.mp4": str(path)},
        subject="Gramsci", api_key="fake-secret",
        model="fake-gemini", consent=True,
        first_scene=4, max_scenes=1,
    )
    assert report["version"] == 2
    assert report["api_requests"] == 1
    assert report["assessed"] == 1
    assert report["results"][0]["verdict"] == "uncertain"
    assert report["results"][0]["recommended_action"] == "buscar_alternativa"
    assert report["human_approved"] is False
    assert report["publishing_permitted"] is False
    prompt = observed[0][1][0]
    assert "Cena 3: grupos podem mudar isso sem" in prompt
    assert "Cena 4: precisar de revoluções violentas" in prompt
    assert "Uma metáfora NUNCA é prova" in prompt
    assert "fake-secret" not in str(report)


def test_ui_shows_full_reason_and_rejects_stale_old_version():
    source = (
        Path(__file__).parents[2] / "webui" / "rick_editorial_panel.py"
    ).read_text(encoding="utf-8")
    assert 'stored.get("version") != 2' in source
    assert "Ler a análise completa da cena" in source
    assert "Correspondência" not in source or "revisar" in source.lower()
    assert "Ação recomendada" not in source or "buscar" in source.lower()
