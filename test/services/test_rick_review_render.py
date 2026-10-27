"""Offline Rick reviewed-export tests: mocks only, no network or FFmpeg."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.rick_editorial_workspace import (
    load_review_workspace, save_editorial_workspace_review,
)
from app.services.rick_review_render import (
    export_reviewed_video, prepare_reviewed_export,
)


def _sample(tmp_path, *, approve=True, subtitles=False):
    root = tmp_path / "tasks"
    folder = root / "sample"
    folder.mkdir(parents=True)
    manifest = {
        "script": "Cena um e cena dois.",
        "params": {
            "video_subject": "Experimento local",
            "subtitle_enabled": subtitles,
            "font_name": "BeVietnamPro-Bold.ttf",
            "video_clip_duration": 2,
        },
        "rick_scene_candidate_preview": {
            "scene_count": 2,
            "status": "preview_only_not_rendered",
            "alignment": "estimated",
            "scenes": [
                {"scene_number": 1, "start_seconds": 0, "end_seconds": 2,
                 "text": "Primeira", "search_term": "sky",
                 "assigned_material_file": "sky.mp4",
                 "match_status": "term_match_unverified"},
                {"scene_number": 2, "start_seconds": 2, "end_seconds": 4,
                 "text": "Segunda", "search_term": "sea",
                 "assigned_material_file": "sea.mp4",
                 "match_status": "term_match_unverified"},
            ],
        },
        "material_sources": [
            {"local_file": name, "provider": "pixabay", "search_term": name}
            for name in ("sky.mp4", "sea.mp4")
        ],
    }
    (folder / "script.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "audio.mp3").write_bytes(b"original audio")
    (folder / "final-1.mp4").write_bytes(b"DO-NOT-REPLACE")
    files = [folder / "sky.mp4", folder / "sea.mp4"]
    for file in files:
        file.write_bytes(b"synthetic file stub")
    workspace = load_review_workspace(root, "sample", [str(p) for p in files])
    if approve:
        choices = [
            {"scene_number": idx, "decision": "approve", "selected_file": file.name,
             "source_note": "Licença e correspondência revisadas manualmente",
             "content_checked": True, "rights_checked": True}
            for idx, file in enumerate(files, start=1)
        ]
        report = save_editorial_workspace_review(
            root, "sample", workspace["preview_sha256"],
            [str(p) for p in files], choices,
        )
        assert report["status"] == "ready_human_reviewed"
    return root, folder, files


def test_approved_review_drives_exact_scene_timeline(tmp_path, monkeypatch):
    root, folder, files = _sample(tmp_path)
    monkeypatch.setattr(
        "app.services.rick_review_render.voice.get_audio_duration",
        lambda _: 4.0,
    )
    result = prepare_reviewed_export(root, "sample")
    assert result["timeline"]["status"] == "ready_metadata_only"
    assert [s["source_file"] for s in result["timeline"]["segments"]] == [
        "sky.mp4", "sea.mp4",
    ]
    assert result["params"].bgm_volume == 0
    assert result["params"].subtitle_enabled is False
    assert result["paths"] == [str(p.resolve()) for p in files]


def test_incomplete_review_blocks_before_any_media_render(tmp_path, monkeypatch):
    root, _, _ = _sample(tmp_path, approve=False)
    monkeypatch.setattr(
        "app.services.rick_review_render.video.combine_videos",
        lambda **_: pytest.fail("No rendering with an incomplete review"),
    )
    with pytest.raises(ValueError, match="Aprove TODAS"):
        export_reviewed_video(root, "sample")


def test_changed_manifest_invalidates_saved_review(tmp_path, monkeypatch):
    root, folder, _ = _sample(tmp_path)
    manifest_file = folder / "script.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["rick_scene_candidate_preview"]["scenes"][0]["text"] = "Alterado"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="Aprove TODAS"):
        prepare_reviewed_export(root, "sample")


def test_audio_duration_mismatch_blocks(tmp_path, monkeypatch):
    root, _, _ = _sample(tmp_path)
    monkeypatch.setattr(
        "app.services.rick_review_render.voice.get_audio_duration",
        lambda _: 5.2,
    )
    with pytest.raises(ValueError, match="duração"):
        prepare_reviewed_export(root, "sample")


def test_deleted_source_blocks(tmp_path, monkeypatch):
    root, _, files = _sample(tmp_path)
    files[1].unlink()
    monkeypatch.setattr(
        "app.services.rick_review_render.voice.get_audio_duration",
        lambda _: 4.0,
    )
    with pytest.raises(ValueError, match="bloqueada"):
        prepare_reviewed_export(root, "sample")


def test_absent_subtitles_block_unless_explicitly_disabled(tmp_path, monkeypatch):
    root, _, _ = _sample(tmp_path, subtitles=True)
    monkeypatch.setattr(
        "app.services.rick_review_render.voice.get_audio_duration",
        lambda _: 4.0,
    )
    with pytest.raises(ValueError, match="subtitle.srt"):
        prepare_reviewed_export(root, "sample")
    result = prepare_reviewed_export(root, "sample", without_subtitles=True)
    assert result["subtitle"] == ""


def test_mock_export_never_overwrites_original_or_calls_remote(tmp_path, monkeypatch):
    root, folder, _ = _sample(tmp_path)
    monkeypatch.setattr(
        "app.services.rick_review_render.voice.get_audio_duration",
        lambda _: 4.0,
    )
    recordings = []

    def combine(**kwargs):
        recordings.append(kwargs)
        Path(kwargs["combined_video_path"]).write_bytes(b"new combined")
        kwargs["used_video_paths"].extend(kwargs["video_paths"])
        return kwargs["combined_video_path"]

    def finalize(**kwargs):
        assert kwargs["bgm_file_override"] == ""
        assert kwargs["params"].subtitle_enabled is False
        Path(kwargs["output_file"]).write_bytes(b"new final")
        return True

    monkeypatch.setattr("app.services.rick_review_render.video.combine_videos", combine)
    monkeypatch.setattr("app.services.rick_review_render.video.generate_video", finalize)
    out = export_reviewed_video(root, "sample")
    assert Path(out["output"]).is_file()
    assert Path(out["report"]).is_file()
    assert out["status"] == "rendered_from_human_review"
    assert recordings[0]["scene_timeline"]["segment_count"] == 2
    assert recordings[0]["clip_speed"] == 1.0
    assert (folder / "final-1.mp4").read_bytes() == b"DO-NOT-REPLACE"
    assert (folder / "rick_editorial_review.json").is_file()
    assert out["used_source_basenames"] == ["sky.mp4", "sea.mp4"]


def test_refuses_symlinked_narration(tmp_path, monkeypatch):
    root, folder, _ = _sample(tmp_path)
    (folder / "audio.mp3").unlink()
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"audio")
    try:
        (folder / "audio.mp3").symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation not available in this Windows environment")
    with pytest.raises(ValueError, match="não autorizado"):
        prepare_reviewed_export(root, "sample")
