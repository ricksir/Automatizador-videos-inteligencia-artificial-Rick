"""Opt-in multimodal QA: no network calls, credentials or approval in tests."""
from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from app.services import rick_semantic_frame_review as review


def _scene(number=1, file="clip.mp4"):
    return {
        "scene_number": number,
        "text": "O parlamento debatendo uma lei",
        "primary": file,
        "metadata_score": 82,
        "human_approved": False,
    }


def _media(tmp_path, file="clip.mp4"):
    p = tmp_path / file
    p.write_bytes(b"mock locally validated media")
    return {file: str(p)}


def _install_genai(monkeypatch, *, answer=None, fail=False, captured=None):
    captured = captured if captured is not None else []
    answer = answer or {
        "verdict": "plausible",
        "visible_evidence": "Pessoas em uma sala de debates",
        "reason": "Os quadros parecem tratar de uma reunião",
    }

    class Client:
        def __init__(self, *, api_key):
            assert api_key == "fake-key"
            self.models = self

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def generate_content(self, *, model, contents, config):
            captured.append((model, contents, config))
            if fail:
                raise RuntimeError("API key fake-key is invalid")
            return types.SimpleNamespace(text=json.dumps(answer))

    class Part:
        @classmethod
        def from_bytes(cls, *, data, mime_type):
            assert data == b"jpegfake"
            assert mime_type == "image/jpeg"
            return (mime_type, data)

    google = types.ModuleType("google")
    genai = types.ModuleType("google.genai")
    genai.Client = Client
    t = types.SimpleNamespace(
        Part=Part,
        GenerateContentConfig=lambda **kwargs: kwargs,
    )
    genai.types = t
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    return captured


def test_consent_required_before_importing_sdk_or_extraction():
    with pytest.raises(ValueError, match="consent_required"):
        review.review_scene_frames(
            {"scenes": [_scene()]}, {}, subject="Política",
            api_key="fake-key", model="configured-model",
        )


@pytest.mark.parametrize("value", [None, "not json", "[]", "{}", '{"verdict":"yes"}'])
def test_rejects_unstructured_or_overconfident_responses(value):
    with pytest.raises(ValueError, match="invalid_model_response"):
        review._parse_assessment(value)


def test_result_is_bounded_and_not_an_approval():
    parsed = review._parse_assessment(json.dumps({
        "verdict": "uncertain",
        "visible_evidence": "Debate em assembleia",
        "reason": "O país não é identificado",
    }))
    assert parsed["verdict"] == "uncertain"
    assert "país não é identificado" in parsed["reason"]


def test_gemini_receives_only_two_jpeg_frames_and_short_scene_text(tmp_path, monkeypatch):
    calls = _install_genai(monkeypatch)
    shots = []
    def frame(path, seconds):
        shots.append((path.name, seconds))
        return b"jpegfake"
    monkeypatch.setattr(review, "_color_frame", frame)
    scenes = [_scene(1), _scene(2)]
    report = review.review_scene_frames(
        {"scenes": scenes}, _media(tmp_path),
        subject="Congresso", api_key="fake-key",
        model="configured-model", consent=True, max_scenes=2,
    )
    assert len(calls) == 2
    assert all(len(call[1]) == 3 for call in calls)
    assert calls[0][1][0].startswith("Você é um assistente")
    assert len(shots) == 4
    assert report["assessed"] == 2
    assert report["api_requests"] == 2
    assert report["human_approved"] is False
    assert report["publishing_permitted"] is False
    assert report["semantic_content_verified"] is False
    assert scenes[0]["human_approved"] is False


def test_batch_only_reviews_selected_six_scenes(tmp_path, monkeypatch):
    calls = _install_genai(monkeypatch)
    monkeypatch.setattr(review, "_color_frame", lambda *_: b"jpegfake")
    scenes = [_scene(n) for n in range(1, 25)]
    report = review.review_scene_frames(
        {"scenes": scenes}, _media(tmp_path),
        subject="Gramsci", api_key="fake-key", model="configured-model",
        consent=True, first_scene=13, max_scenes=6,
    )
    assert report["attempted"] == 6
    assert len(calls) == 6
    assert [r["scene_number"] for r in report["results"]] == list(range(13, 19))


def test_unavailable_media_does_not_call_remote_provider(tmp_path, monkeypatch):
    calls = _install_genai(monkeypatch)
    report = review.review_scene_frames(
        {"scenes": [_scene()]},
        {"clip.mp4": str(tmp_path / "nonexistent.mp4")},
        subject="História", api_key="fake-key", model="configured-model",
        consent=True,
    )
    assert report["api_requests"] == 0
    assert calls == []
    assert report["results"][0]["status"] == "invalid_local_media"


def test_provider_exception_is_fail_closed_and_never_leaks_key(
    tmp_path, monkeypatch,
):
    _install_genai(monkeypatch, fail=True)
    monkeypatch.setattr(review, "_color_frame", lambda *_: b"jpegfake")
    report = review.review_scene_frames(
        {"scenes": [_scene()]}, _media(tmp_path),
        subject="História", api_key="fake-key", model="configured-model",
        consent=True,
    )
    assert report["api_requests"] == 1
    assert report["results"][0]["status"] == "provider_or_response_failure"
    assert report["results"][0]["verdict"] == "uncertain"
    assert "fake-key" not in str(report)


def test_invalid_model_response_does_not_become_verification(
    tmp_path, monkeypatch,
):
    _install_genai(monkeypatch, answer={
        "verdict": "guaranteed", "visible_evidence": "x", "reason": "y",
    })
    monkeypatch.setattr(review, "_color_frame", lambda *_: b"jpegfake")
    report = review.review_scene_frames(
        {"scenes": [_scene()]}, _media(tmp_path),
        subject="História", api_key="fake-key", model="configured-model",
        consent=True,
    )
    assert report["results"][0]["status"] == "provider_or_response_failure"
    assert report["human_approved"] is False


@pytest.mark.parametrize("limit", [0, 7, True, -1])
def test_rejects_unbounded_requests(tmp_path, limit):
    with pytest.raises(ValueError, match="semantic_review_configuration_invalid"):
        review.review_scene_frames(
            {"scenes": [_scene()]}, _media(tmp_path),
            subject="História", api_key="fake-key", model="configured-model",
            consent=True, max_scenes=limit,
        )


def test_extraction_real_ffmpeg_color_frames(tmp_path):
    from imageio_ffmpeg import get_ffmpeg_exe
    output = tmp_path / "local.mp4"
    subprocess.run([
        get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
        "-nostdin", "-y", "-f", "lavfi", "-i",
        "color=c=red:s=320x480:r=10:d=2",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output),
    ], check=True, timeout=30, stdout=subprocess.DEVNULL)
    frame = review._color_frame(output, 0.3)
    assert frame.startswith(b"\xff\xd8")
    assert len(frame) <= 160_000


def test_webui_hard_requires_consent_and_never_calls_api_on_load():
    code = (Path(__file__).parents[2] / "webui" / "rick_editorial_panel.py").read_text(
        encoding="utf-8"
    )
    assert "Autorizo o envio externo" in code
    assert "disabled=not (authorized and key_ready and model_name)" in code
    assert "review_scene_frames(" in code
    assert "Analisar este lote com IA visual" in code
