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


def _cache(root: Path) -> Path:
    return root.parent / "trusted-cache"


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
    cache = _cache(root)
    cache.mkdir()
    files = [cache / "sky.mp4", cache / "sea.mp4"]
    for file in files:
        file.write_bytes(b"synthetic file stub")
    # A restarted task may have no transient state.materials. The UI and
    # CLI explicitly supply the app-controlled cache for recovery.
    workspace = load_review_workspace(root, "sample", [], cache_dir=cache)
    if approve:
        choices = [
            {"scene_number": idx, "decision": "approve", "selected_file": file.name,
             "source_note": "Licença e correspondência revisadas manualmente",
             "content_checked": True, "rights_checked": True}
            for idx, file in enumerate(files, start=1)
        ]
        report = save_editorial_workspace_review(
            root, "sample", workspace["preview_sha256"],
            [str(p) for p in files], choices, cache_dir=cache,
        )
        assert report["status"] == "ready_human_reviewed"
    return root, folder, files


def test_approved_review_drives_exact_scene_timeline(tmp_path, monkeypatch):
    root, folder, files = _sample(tmp_path)
    monkeypatch.setattr(
        "app.services.rick_review_render.voice.get_audio_duration",
        lambda _: 4.0,
    )
    result = prepare_reviewed_export(root, "sample", cache_dir=_cache(root))
    assert result["timeline"]["status"] == "ready_metadata_only"
    assert [s["source_file"] for s in result["timeline"]["segments"]] == [
        "sky.mp4", "sea.mp4",
    ]
    assert result["params"].bgm_volume == 0
    assert result["params"].subtitle_enabled is False
    assert result["paths"] == [str(p.resolve()) for p in files]




def test_export_media_order_follows_saved_scene_approvals(tmp_path, monkeypatch):
    """Cache iteration order cannot change approved render input order."""
    root, _, files = _sample(tmp_path, approve=False)
    ws = load_review_workspace(root, "sample", [], cache_dir=_cache(root))
    review = save_editorial_workspace_review(
        root, "sample", ws["preview_sha256"], [str(p) for p in files],
        [
            {"scene_number": idx, "decision": "approve", "selected_file": name,
             "source_note": "Clip checked by a human", "content_checked": True,
             "rights_checked": True}
            for idx, name in enumerate(("sea.mp4", "sky.mp4"), start=1)
        ],
        cache_dir=_cache(root),
    )
    assert review["status"] == "ready_human_reviewed"
    monkeypatch.setattr(
        "app.services.rick_review_render.voice.get_audio_duration",
        lambda _: 4.0,
    )
    preflight = prepare_reviewed_export(root, "sample", cache_dir=_cache(root))
    assert preflight["paths"] == [str(files[1].resolve()), str(files[0].resolve())]
    assert [item["source_file"] for item in preflight["timeline"]["segments"]] == [
        "sea.mp4", "sky.mp4",
    ]


def test_reused_approved_clip_does_not_include_unused_cached_media(tmp_path, monkeypatch):
    """Unrelated cached material is not an input to reviewed rendering."""
    root, _, files = _sample(tmp_path, approve=False)
    ws = load_review_workspace(root, "sample", [], cache_dir=_cache(root))
    review = save_editorial_workspace_review(
        root, "sample", ws["preview_sha256"], [str(p) for p in files],
        [
            {"scene_number": idx, "decision": "approve", "selected_file": "sky.mp4",
             "source_note": "Clip checked by a human", "content_checked": True,
             "rights_checked": True}
            for idx in (1, 2)
        ],
        cache_dir=_cache(root),
    )
    assert review["status"] == "ready_human_reviewed"
    monkeypatch.setattr(
        "app.services.rick_review_render.voice.get_audio_duration",
        lambda _: 4.0,
    )
    preflight = prepare_reviewed_export(root, "sample", cache_dir=_cache(root))
    assert preflight["paths"] == [str(files[0].resolve())]
    assert [item["source_file"] for item in preflight["timeline"]["segments"]] == [
        "sky.mp4", "sky.mp4",
    ]


def test_incomplete_review_blocks_before_any_media_render(tmp_path, monkeypatch):
    root, _, _ = _sample(tmp_path, approve=False)
    monkeypatch.setattr(
        "app.services.rick_review_render.video.combine_videos",
        lambda **_: pytest.fail("No rendering with an incomplete review"),
    )
    with pytest.raises(ValueError, match="Aprove TODAS"):
        export_reviewed_video(root, "sample", cache_dir=_cache(root))


def test_changed_manifest_invalidates_saved_review(tmp_path, monkeypatch):
    root, folder, _ = _sample(tmp_path)
    manifest_file = folder / "script.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["rick_scene_candidate_preview"]["scenes"][0]["text"] = "Alterado"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="Aprove TODAS"):
        prepare_reviewed_export(root, "sample", cache_dir=_cache(root))


def test_audio_duration_mismatch_blocks(tmp_path, monkeypatch):
    root, _, _ = _sample(tmp_path)
    monkeypatch.setattr(
        "app.services.rick_review_render.voice.get_audio_duration",
        lambda _: 5.2,
    )
    with pytest.raises(ValueError, match="duração"):
        prepare_reviewed_export(root, "sample", cache_dir=_cache(root))


def test_deleted_source_blocks(tmp_path, monkeypatch):
    root, _, files = _sample(tmp_path)
    files[1].unlink()
    monkeypatch.setattr(
        "app.services.rick_review_render.voice.get_audio_duration",
        lambda _: 4.0,
    )
    with pytest.raises(ValueError, match="bloqueada"):
        prepare_reviewed_export(root, "sample", cache_dir=_cache(root))


def test_absent_subtitles_block_unless_explicitly_disabled(tmp_path, monkeypatch):
    root, _, _ = _sample(tmp_path, subtitles=True)
    monkeypatch.setattr(
        "app.services.rick_review_render.voice.get_audio_duration",
        lambda _: 4.0,
    )
    with pytest.raises(ValueError, match="subtitle.srt"):
        prepare_reviewed_export(root, "sample", cache_dir=_cache(root))
    result = prepare_reviewed_export(root, "sample", cache_dir=_cache(root), without_subtitles=True)
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
    out = export_reviewed_video(root, "sample", cache_dir=_cache(root))
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
        prepare_reviewed_export(root, "sample", cache_dir=_cache(root))


def test_export_rejects_missing_explicit_cache_even_if_review_is_saved(tmp_path, monkeypatch):
    root, _, _ = _sample(tmp_path)
    monkeypatch.setattr(
        "app.services.rick_review_render.voice.get_audio_duration",
        lambda _: 4.0,
    )
    with pytest.raises(ValueError, match="cache confiável"):
        prepare_reviewed_export(root, "sample")


def test_task_folder_files_do_not_replace_missing_approved_cache_assets(tmp_path, monkeypatch):
    root, folder, files = _sample(tmp_path)
    for original in files:
        (folder / original.name).write_bytes(original.read_bytes())
        original.unlink()
    monkeypatch.setattr(
        "app.services.rick_review_render.voice.get_audio_duration",
        lambda _: 4.0,
    )
    with pytest.raises(ValueError, match="bloqueada"):
        prepare_reviewed_export(root, "sample", cache_dir=_cache(root))


def test_export_rejects_cached_symlink_to_external_file(tmp_path, monkeypatch):
    root, _, files = _sample(tmp_path)
    outside = tmp_path / "external-video.mp4"
    outside.write_bytes(b"external file")
    files[1].unlink()
    try:
        files[1].symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("Symlinks disabled in this environment")
    monkeypatch.setattr(
        "app.services.rick_review_render.voice.get_audio_duration",
        lambda _: 4.0,
    )
    with pytest.raises(ValueError, match="bloqueada"):
        prepare_reviewed_export(root, "sample", cache_dir=_cache(root))
