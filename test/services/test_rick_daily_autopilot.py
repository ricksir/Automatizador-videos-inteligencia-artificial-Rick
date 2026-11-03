"""Daily Rick autopilot safety, idempotency and publication tests — no APIs."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import rick_daily_autopilot as daily


DAY = date(2026, 11, 4)


def _policy(**overrides):
    policy = {
        "version": 1,
        "enabled": True,
        "publish_enabled": True,
        "timezone": "America/Sao_Paulo",
        "start_date": "2026-11-04",
        "topics": ["Uma curiosidade histórica sobre o rádio"],
        "platforms": ["youtube", "instagram", "tiktok"],
        "video_params": {"video_source": "pexels", "voice_name": "pt-BR-AntonioNeural"},
    }
    policy.update(overrides)
    return policy


def _generator(folder: Path, counters: list):
    def create(topic, template, task_id):
        counters.append((topic, task_id))
        file = folder / "final.mp4"
        file.write_bytes(b"synthetic-output")
        return {"video_path": str(file), "quality_receipt": None}
    return create


def _technical_probe(monkeypatch):
    monkeypatch.setattr(daily, "validate_video", lambda path: {
        "video_sha256": "a" * 64, "duration_seconds": 42.0,
        "resolution": [1080, 1920],
    })
    monkeypatch.setattr(daily.upload_post, "upload_post_service",
                        SimpleNamespace(auto_upload=False))


def test_default_is_disabled_and_no_generation(tmp_path):
    calls = []
    assert daily.run_once(
        _policy(enabled=False), tmp_path / "state", today=DAY,
        generate=lambda *a: calls.append("bad")
    ) == {"status": "disabled"}
    assert calls == []
    assert not (tmp_path / "state").exists()


def test_automatic_daily_publish_once_per_platform(monkeypatch, tmp_path):
    _technical_probe(monkeypatch)
    calls, uploads = [], []
    policy = _policy()
    generate = _generator(tmp_path, calls)

    def publish(platform, path, title):
        uploads.append((platform, Path(path).name, title))
        return {"success": True, "request_id": "req-" + platform}

    state = tmp_path / "state"
    first = daily.run_once(policy, state, today=DAY, generate=generate,
                           publish=publish, quality_check=lambda *_: True)
    assert first["status"] == "published"
    assert list(first["platforms"].values()) == ["published"] * 3
    assert len(calls) == 1
    assert [upload[0] for upload in uploads] == ["youtube", "instagram", "tiktok"]
    assert first["publish_requests"] == {
        platform: "req-" + platform for platform in policy["platforms"]
    }
    second = daily.run_once(policy, state, today=DAY, generate=generate,
                            publish=publish, quality_check=lambda *_: True)
    assert second["status"] == "published"
    assert len(calls) == 1
    assert len(uploads) == 3, "A second daily run must never repost"
    assert list(state.glob("*.json")) == [state / "2026-11-04.json"]


def test_ambiguous_upload_cannot_be_automatically_retried(monkeypatch, tmp_path):
    _technical_probe(monkeypatch)
    calls = []
    posts = []

    def publish(platform, _video, _title):
        posts.append(platform)
        if platform == "youtube":
            return {
                "success": False, "request_id": "may-have-been-posted",
                "error": "connection timeout; unconfirmed",
            }
        return {"success": True, "request_id": "ok-" + platform}

    state = tmp_path / "ledger"
    first = daily.run_once(_policy(), state, today=DAY,
                           generate=_generator(tmp_path, calls),
                           publish=publish, quality_check=lambda *_: True)
    assert first["status"] == "publication_incomplete"
    assert first["platforms"] == {
        "youtube": "unknown", "instagram": "published", "tiktok": "published"
    }
    daily.run_once(_policy(), state, today=DAY,
                   generate=lambda *_: pytest.fail("Unexpected regeneration"),
                   publish=publish, quality_check=lambda *_: True)
    assert posts == ["youtube", "instagram", "tiktok"]


def test_crash_before_result_never_regenerates(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "2026-11-04.json").write_text(json.dumps({
        "version": 1, "date": "2026-11-04",
        "topic": _policy()["topics"][0], "status": "rendering",
        "task_id": "historic", "platforms": {p: "not_started" for p in _policy()["platforms"]},
    }), encoding="utf-8")
    result = daily.run_once(
        _policy(), state, today=DAY,
        generate=lambda *_: pytest.fail("Unconfirmed generation was replayed")
    )
    assert result["status"] == "generation_unconfirmed"


def test_absent_semantic_rights_receipt_blocks_publication(monkeypatch, tmp_path):
    _technical_probe(monkeypatch)
    posts = []
    result = daily.run_once(
        _policy(), tmp_path / "state", today=DAY,
        generate=_generator(tmp_path, []),
        publish=lambda *args: posts.append(args),
    )
    assert result["status"] == "quality_blocked"
    assert not posts
    assert "Sem laudo" in result["error"]


def test_no_publication_without_explicit_consent(monkeypatch, tmp_path):
    _technical_probe(monkeypatch)
    posts = []
    result = daily.run_once(
        _policy(publish_enabled=False), tmp_path / "state", today=DAY,
        generate=_generator(tmp_path, []),
        quality_check=lambda *_: True,
        publish=lambda *args: posts.append(args),
    )
    assert result["status"] == "ready_not_authorized"
    assert posts == []


def test_existing_submission_is_not_sent_twice(monkeypatch, tmp_path):
    _technical_probe(monkeypatch)
    state = tmp_path / "state"
    state.mkdir()
    path = tmp_path / "video.mp4"
    path.write_bytes(b"pretend")
    (state / "2026-11-04.json").write_text(json.dumps({
        "version": 1,
        "date": "2026-11-04", "topic": _policy()["topics"][0],
        "status": "publishing", "task_id": "rick-daily",
        "video_path": str(path),
        "platforms": {
            "youtube": "submitting", "instagram": "not_started",
            "tiktok": "published",
        },
        "publish_requests": {"tiktok": "done"},
    }), encoding="utf-8")
    posts = []
    result = daily.run_once(
        _policy(), state, today=DAY,
        generate=lambda *_: pytest.fail("No new video should be generated"),
        publish=lambda platform, *_: (posts.append(platform) or {"success": True}),
    )
    assert result["status"] == "publication_incomplete"
    assert result["platforms"]["youtube"] == "submitting"
    assert result["platforms"]["instagram"] == "published"
    assert posts == ["instagram"]


def test_concurrent_lock_blocks_execution(tmp_path):
    folder = tmp_path / "state"
    folder.mkdir()
    (folder / ".rick-daily.lock").write_text("pid=someone-else", encoding="utf-8")
    with pytest.raises(RuntimeError, match="execução"):
        daily.run_once(_policy(), folder, today=DAY)
    assert not (folder / "2026-11-04.json").exists()


def test_exhausted_topic_bank_does_not_loop():
    with pytest.raises(ValueError, match="esgotado"):
        daily._topic_for_day(_policy(), date(2026, 11, 5))


def test_quality_receipt_requires_every_gate(tmp_path):
    file = tmp_path / "qa.json"
    content = {
        "version": 1, "status": "passed", "video_sha256": "a" * 64,
        "semantic_scene_match": True, "audio_timing_verified": True,
        "source_rights_verified": True, "no_unsafe_content": True,
        "qa_engine": "verified-scene-engine-v1",
    }
    file.write_text(json.dumps(content), encoding="utf-8")
    assert daily.verify_quality_receipt(file, "a" * 64)
    assert not daily.verify_quality_receipt(file, "b" * 64)
    for key in ("semantic_scene_match", "audio_timing_verified",
                "source_rights_verified", "no_unsafe_content"):
        invalid = dict(content, **{key: False})
        file.write_text(json.dumps(invalid), encoding="utf-8")
        assert not daily.verify_quality_receipt(file, "a" * 64)
    file.write_text(json.dumps({**content, "qa_engine": "metadata_only"}),
                    encoding="utf-8")
    assert not daily.verify_quality_receipt(file, "a" * 64)


def test_policy_validation_does_not_enable_upload_by_default(tmp_path):
    original = _policy(enabled=False, publish_enabled=False)
    file = tmp_path / "policy.json"
    file.write_text(json.dumps(original), encoding="utf-8")
    assert daily.load_policy(file)["publish_enabled"] is False

    for mutation in (
        {"platforms": ["youtube", "youtube"]},
        {"video_params": {"video_source": "unknown"}},
        {"video_params": {"video_source": "pexels", "video_count": 2}},
        {"video_params": {"video_source": "pexels", "custom_audio_file": "x.mp3"}},
        {"enabled": "true"},
    ):
        file.write_text(json.dumps({**original, **mutation}), encoding="utf-8")
        with pytest.raises(ValueError):
            daily.load_policy(file)


def test_probe_requires_vertical_h264_aac(monkeypatch, tmp_path):
    video = tmp_path / "result.mp4"
    video.write_bytes(b"FAKE-MP4")

    def fake_probe(*_args, **_kwargs):
        return SimpleNamespace(stdout=json.dumps({
            "format": {"duration": "41.2"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264",
                 "width": 1080, "height": 1920},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        }))

    monkeypatch.setattr(daily.subprocess, "run", fake_probe)
    details = daily.validate_video(video)
    assert details["resolution"] == [1080, 1920]
    assert details["duration_seconds"] == 41.2

    def invalid_probe(*_args, **_kwargs):
        return SimpleNamespace(stdout=json.dumps({
            "format": {"duration": "41.2"},
            "streams": [{"codec_type": "video", "codec_name": "h264",
                         "width": 1920, "height": 1080}],
        }))
    monkeypatch.setattr(daily.subprocess, "run", invalid_probe)
    with pytest.raises(ValueError, match="vertical"):
        daily.validate_video(video)
