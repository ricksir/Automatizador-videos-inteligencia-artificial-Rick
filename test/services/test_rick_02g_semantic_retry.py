"""Rerun only failed Gemini assessments; do not re-charge completed scenes."""
from __future__ import annotations

import json
import sys
import types
from copy import deepcopy
from pathlib import Path

import pytest

from app.services import rick_semantic_frame_review as gemini
from app.services import rick_semantic_retry as retry


def _result(n, file=None, *, status="ai_assessment_for_human_review"):
    return {
        "scene_number": n, "file": file or f"clip{n}.mp4",
        "status": status,
        "verdict": "uncertain",
        "visual_relation": "insufficient",
        "visible_evidence": "" if status != "ai_assessment_for_human_review"
        else "Pessoas em uma sala",
        "reason": "" if status != "ai_assessment_for_human_review"
        else "Não corresponde ao contexto",
    }


def _previous():
    return {
        "version": 2, "model": "fake-gemini",
        "attempted": 6, "assessed": 5, "api_requests": 6,
        "results": [
            _result(1),
            _result(2, status="provider_or_response_failure"),
            *[_result(n) for n in range(3, 7)],
        ],
        "human_approved": False,
        "publishing_permitted": False,
    }


def test_selects_only_failed_scenes():
    previous = _previous()
    assert retry.failed_scene_numbers(previous) == [2]


def test_merge_replaces_failed_scene_and_preserves_all_five_others():
    previous = _previous()
    before = deepcopy(previous)
    result = retry.merge_failed_scene_retry(
        previous, {
            "version": 2, "model": "fake-gemini",
            "api_requests": 1, "results": [_result(2)],
        },
    )
    assert result["api_requests"] == 7
    assert result["retry_api_requests"] == 1
    assert result["assessed"] == 6
    assert result["attempted"] == 6
    assert result["results"][1]["status"] == "ai_assessment_for_human_review"
    assert all(
        result["results"][i] == previous["results"][i]
        for i in [0, 2, 3, 4, 5]
    )
    assert previous == before
    assert not result["human_approved"]
    assert not result["publishing_permitted"]
    assert not result["semantic_content_verified"]


def test_retry_failure_can_be_retried_again_without_claiming_approval():
    result = retry.merge_failed_scene_retry(
        _previous(), {
            "version": 2, "model": "fake-gemini", "api_requests": 1,
            "results": [_result(
                2, status="provider_or_response_failure",
            )],
        },
    )
    assert result["assessed"] == 5
    assert retry.failed_scene_numbers(result) == [2]


@pytest.mark.parametrize("wrong", [
    {"version": 1, "model": "fake-gemini", "api_requests": 1, "results": []},
    {"version": 2, "model": "another-model", "api_requests": 1, "results": []},
    {"version": 2, "model": "fake-gemini", "api_requests": 7, "results": []},
])
def test_refuses_invalid_retry(wrong):
    with pytest.raises(ValueError, match="incompatível"):
        retry.merge_failed_scene_retry(_previous(), wrong)


def test_no_overwriting_good_assessment_or_different_file():
    for wrong in [
        _result(1), _result(2, file="other.mp4"),
    ]:
        with pytest.raises(ValueError, match="não corresponde"):
            retry.merge_failed_scene_retry(
                _previous(),
                {"version": 2, "model": "fake-gemini",
                 "api_requests": 1, "results": [wrong]},
            )


def test_only_scene_numbers_cannot_be_empty_or_duplicates():
    base = {
        "scenes": [{
            "scene_number": n, "text": "Uma frase", "primary": "a.mp4",
        } for n in range(1, 7)]
    }
    for numbers in [[], [2, 2], [0], [61], [True], list(range(1, 7))]:
        # The six-scene list only becomes invalid for the five-scene cap.
        cap = 5 if len(numbers) == 6 else 6
        with pytest.raises(ValueError, match="semantic_review_configuration_invalid"):
            gemini.review_scene_frames(
                base, {}, subject="Tema", api_key="fake-key",
                model="fake-gemini", consent=True,
                max_scenes=cap, only_scene_numbers=numbers,
            )


def test_single_explicit_retry_makes_only_one_api_call(
    tmp_path, monkeypatch,
):
    from app.services import rick_semantic_frame_review as target

    calls = []
    class Client:
        def __init__(self, *, api_key):
            assert api_key == "fake-key"
            self.models = self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def generate_content(self, *, model, contents, config):
            calls.append(contents)
            return types.SimpleNamespace(text=json.dumps({
                "verdict": "uncertain",
                "visual_relation": "contextual",
                "visible_evidence": "Vê-se um edifício",
                "reason": "Edifício genérico não permite concluir",
            }))

    class Part:
        @classmethod
        def from_bytes(cls, *, data, mime_type):
            assert data == b"fake-image"
            assert mime_type == "image/jpeg"
            return (mime_type, data)

    google = types.ModuleType("google")
    genai = types.ModuleType("google.genai")
    genai.Client = Client
    genai.types = types.SimpleNamespace(
        Part=Part, GenerateContentConfig=lambda **kw: kw,
    )
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setattr(target, "_color_frame", lambda *_: b"fake-image")
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"local only")
    sample = {
        "scenes": [
            {"scene_number": n, "text": "Um assunto muito importante",
             "primary": "a.mp4"}
            for n in range(1, 7)
        ]
    }
    result = target.review_scene_frames(
        sample, {"a.mp4": str(clip)},
        subject="Gramsci", api_key="fake-key", model="fake-gemini",
        consent=True, first_scene=1, max_scenes=1, only_scene_numbers=[2],
    )
    assert result["attempted"] == 1
    assert result["api_requests"] == 1
    assert result["results"][0]["scene_number"] == 2
    assert len(calls) == 1
    assert "Cena 1:" in calls[0][0]


@pytest.mark.parametrize("status,expected", [
    (400, "invalid_request"),
    (401, "credential_or_permission"),
    (403, "credential_or_permission"),
    (404, "model_not_found"),
    (408, "timeout_or_connection"),
    (422, "invalid_request"),
    (429, "quota_or_rate_limit"),
    (500, "provider_unavailable"),
    (503, "provider_unavailable"),
    (504, "timeout_or_connection"),
    (418, "other_http_error"),
])
def test_api_failure_is_classified_by_numeric_status_only(status, expected):
    class ProviderError(Exception):
        def __init__(self):
            self.code = status
        def __str__(self):
            return "secret-key-must-not-be-persisted"

    assert gemini._classify_api_failure(ProviderError()) == expected


def test_api_failure_supports_status_code_and_safe_unknown_fallback():
    class HttpError(Exception):
        status_code = 429
        code = 401

    class ConnectTimeout(Exception):
        pass

    assert gemini._classify_api_failure(HttpError("private URL")) == "quota_or_rate_limit"
    assert gemini._classify_api_failure(ConnectTimeout("secret")) == "timeout_or_connection"
    assert gemini._classify_api_failure(RuntimeError("secret")) == "unclassified_api_error"



def test_failure_stage_differentiates_provider_and_invalid_response(
    tmp_path, monkeypatch,
):
    from app.services import rick_semantic_frame_review as target

    class Client:
        def __init__(self, *, api_key):
            self.models = self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def generate_content(self, *, model, contents, config):
            if model == "raise":
                raise RuntimeError("provider rejected fake-key")
            return types.SimpleNamespace(text="NOT JSON")
    class Part:
        @classmethod
        def from_bytes(cls, *, data, mime_type):
            return (mime_type, data)
    google = types.ModuleType("google")
    genai = types.ModuleType("google.genai")
    genai.Client = Client
    genai.types = types.SimpleNamespace(
        Part=Part, GenerateContentConfig=lambda **kw: kw,
    )
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setattr(target, "_color_frame", lambda *_: b"image")
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"local")
    data = {"scenes": [
        {"scene_number": 1, "primary": "a.mp4", "text": "Frase"},
    ]}
    for model, expected in [
        ("raise", "api_request"), ("json-invalid", "invalid_model_response")
    ]:
        output = target.review_scene_frames(
            data, {"a.mp4": str(clip)},
            subject="Tema", api_key="fake-key", model=model,
            consent=True,
        )
        row = output["results"][0]
        assert row["status"] == "provider_or_response_failure"
        assert row["failure_stage"] == expected
        assert row["failure_kind"] == (
            "unclassified_api_error" if model == "raise" else "invalid_response"
        )
        assert "fake-key" not in str(output)
        assert output["assessed"] == 0


def test_ui_shows_failed_as_technical_and_offers_explicit_retry():
    code = (
        Path(__file__).parents[2] / "webui" / "rick_editorial_panel.py"
    ).read_text(encoding="utf-8")
    assert "Reexecutar apenas cenas sem avaliação válida" in code
    assert "Essas cenas NÃO foram consideradas incertas" in code
    assert "only_scene_numbers=failed" in code
    assert "disabled=not (authorized and key_ready and model_name)" in code
    assert "merge_failed_scene_retry" in code
    assert '"Categoria segura"' in code
    assert "quota_or_rate_limit" in code
    assert "Falha não classificada/anterior à atualização" in code



def test_ui_counts_sdk_invocations_without_claiming_exact_http_attempts():
    code = (
        Path(__file__).parents[2] / "webui" / "rick_editorial_panel.py"
    ).read_text(encoding="utf-8")
    assert "esse contador não mede cada tentativa HTTP" in code
    assert "O SDK pode repetir requisições HTTP automaticamente" in code
    assert "invocações do SDK Gemini, sem contar retentativas" in code
