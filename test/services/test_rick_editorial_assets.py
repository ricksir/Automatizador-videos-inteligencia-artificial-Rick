"""Offline acceptance checks for task-owned human-supplied editorial media."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from app.services.rick_editorial_assets import (
    exclude_editorial_material,
    excluded_editorial_materials,
    import_editorial_material,
    load_editorial_assets,
    restore_editorial_material,
)
from app.services.rick_editorial_workspace import (
    load_review_workspace,
    save_editorial_workspace_review,
)
from app.services.rick_review_render import prepare_reviewed_export

_MP4 = b"\x00\x00\x00\x18ftypisom000000000000"


def _task(tmp_path: Path):
    root = tmp_path / "tasks"
    folder = root / "example"
    folder.mkdir(parents=True)
    manifest = {
        "script": "Uma história curta.",
        "params": {"video_clip_duration": 2, "subtitle_enabled": False},
        "rick_scene_candidate_preview": {
            "scene_count": 2,
            "scenes": [
                {"start_seconds": 0, "end_seconds": 2, "text": "Cena um",
                 "search_term": "history", "assigned_material_file": "generic.mp4"},
                {"start_seconds": 2, "end_seconds": 4, "text": "Cena dois",
                 "search_term": "history", "assigned_material_file": "generic.mp4"},
            ],
        },
        "material_sources": [
            {"local_file": "generic.mp4", "provider": "pixabay", "search_term": "history"}
        ],
    }
    (folder / "script.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "audio.mp3").write_bytes(b"ORIGINAL AUDIO")
    (folder / "original.mp4").write_bytes(b"ORIGINAL VIDEO")
    stock_cache = tmp_path / "cache"
    stock_cache.mkdir()
    stock = stock_cache / "generic.mp4"
    stock.write_bytes(_MP4)
    return root, folder, stock_cache


def _human(number, filename):
    return {
        "scene_number": number,
        "decision": "approve",
        "selected_file": filename,
        "source_note": "Conteúdo e autorização examinados por pessoa",
        "content_checked": True,
        "rights_checked": True,
    }


def test_import_local_video_and_revise_without_touching_original(tmp_path, monkeypatch):
    root, folder, cache = _task(tmp_path)
    before_script = (folder / "script.json").read_bytes()
    original = (folder / "original.mp4").read_bytes()
    filename = import_editorial_material(
        root, "example", "documentary.mp4", _MP4,
        scene_number=1, source_note="Mídia própria; origem e licença a conferir",
    )
    assert filename.startswith("rick-local-")
    paths, metadata = load_editorial_assets(root, "example")
    assert filename in paths
    assert metadata[filename]["provider"] == "Importação local (não verificada)"
    ws = load_review_workspace(root, "example", [], cache_dir=cache)
    assert ws["saved_review"] is None
    assert filename in ws["paths"]
    assert ws["source_metadata"][filename]["source_page"].startswith("Mídia própria")
    assert (folder / "script.json").read_bytes() == before_script
    assert (folder / "original.mp4").read_bytes() == original
    report = save_editorial_workspace_review(
        root, "example", ws["preview_sha256"], list(ws["paths"].values()),
        [_human(1, filename), _human(2, filename)], cache_dir=cache,
    )
    assert report["status"] == "ready_human_reviewed"
    monkeypatch.setattr(
        "app.services.rick_review_render.voice.get_audio_duration", lambda _: 4.0
    )
    planned = prepare_reviewed_export(root, "example", cache_dir=cache)
    assert planned["timeline"]["status"] == "ready_metadata_only"
    assert all(s["source_file"] == filename for s in planned["timeline"]["segments"])
    assert (folder / "script.json").read_bytes() == before_script
    assert (folder / "original.mp4").read_bytes() == original


def test_rejected_clips_are_hidden_task_wide_but_can_be_restored(tmp_path):
    root, folder, cache = _task(tmp_path)
    ws = load_review_workspace(root, "example", [], cache_dir=cache)
    assert "generic.mp4" in ws["paths"]
    exclude_editorial_material(root, "example", "generic.mp4")
    assert excluded_editorial_materials(root, "example") == {"generic.mp4"}
    hidden = load_review_workspace(root, "example", [], cache_dir=cache)
    assert "generic.mp4" not in hidden["paths"]
    assert (cache / "generic.mp4").is_file()
    restore_editorial_material(root, "example", "generic.mp4")
    assert "generic.mp4" in load_review_workspace(
        root, "example", [], cache_dir=cache
    )["paths"]


def test_excluded_previous_approval_blocks_export(tmp_path, monkeypatch):
    root, folder, cache = _task(tmp_path)
    ws = load_review_workspace(root, "example", [], cache_dir=cache)
    report = save_editorial_workspace_review(
        root, "example", ws["preview_sha256"], list(ws["paths"].values()),
        [_human(1, "generic.mp4"), _human(2, "generic.mp4")], cache_dir=cache,
    )
    assert report["status"] == "ready_human_reviewed"
    exclude_editorial_material(root, "example", "generic.mp4")
    monkeypatch.setattr(
        "app.services.rick_review_render.voice.get_audio_duration", lambda _: 4.0
    )
    with pytest.raises(ValueError, match="bloqueada"):
        prepare_reviewed_export(root, "example", cache_dir=cache)
    assert (folder / "original.mp4").read_bytes() == b"ORIGINAL VIDEO"


def test_tampered_local_file_not_selectable_or_approvable(tmp_path):
    root, folder, cache = _task(tmp_path)
    name = import_editorial_material(
        root, "example", "source.mp4", _MP4,
        scene_number=1, source_note="Original com licença conferível",
    )
    ws = load_review_workspace(root, "example", [], cache_dir=cache)
    (Path(ws["paths"][name])).write_bytes(_MP4 + b"CHANGED")
    assert name not in load_editorial_assets(root, "example")[0]
    renewed = load_review_workspace(root, "example", [], cache_dir=cache)
    report = save_editorial_workspace_review(
        root, "example", renewed["preview_sha256"], list(renewed["paths"].values()),
        [_human(1, name)], cache_dir=cache,
    )
    assert report["status"] == "blocked"
    assert report["human_approved_count"] == 0


def test_invalid_names_and_unrelated_payloads_fail_closed(tmp_path):
    root, folder, _ = _task(tmp_path)
    for name, payload in [
        ("../escape.mp4", _MP4),
        ("bad.mov", _MP4),
        ("wrong.mp4", b"not a movie"),
        ("image.png", b"not an image"),
    ]:
        with pytest.raises(ValueError):
            import_editorial_material(
                root, "example", name, payload,
                scene_number=1, source_note="Fonte declarada",
            )
    with pytest.raises(ValueError):
        import_editorial_material(
            root, "example", "clip.mp4", _MP4, scene_number=1, source_note="",
        )
    with pytest.raises(ValueError):
        exclude_editorial_material(root, "example", "../escape.mp4")
    assert not (folder / "rick_editorial_materials.json").exists()


def test_image_import_converts_locally_with_no_external_calls(tmp_path, monkeypatch):
    root, folder, cache = _task(tmp_path)
    blob = io.BytesIO()
    Image.new("RGB", (12, 20), "white").save(blob, format="PNG")
    conversions = []

    def fake_convert(source, target):
        conversions.append(source.suffix)
        target.write_bytes(_MP4)

    monkeypatch.setattr(
        "app.services.rick_editorial_assets._image_to_video", fake_convert
    )
    name = import_editorial_material(
        root, "example", "historical-photo.png", blob.getvalue(),
        scene_number=2, source_note="Arquivo histórico de licença não verificada",
    )
    assert conversions == [".png"]
    assert name in load_review_workspace(root, "example", [], cache_dir=cache)["paths"]
    assert not list((folder / "rick_editorial_assets").glob(".rick-image-*"))


def test_symlinked_editorial_asset_is_rejected(tmp_path):
    root, folder, _ = _task(tmp_path)
    name = import_editorial_material(
        root, "example", "original.mp4", _MP4,
        scene_number=1, source_note="Arquivo de origem declarada",
    )
    paths, _ = load_editorial_assets(root, "example")
    file = Path(paths[name])
    external = tmp_path / "outside.mp4"
    external.write_bytes(_MP4)
    file.unlink()
    try:
        file.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not permitted on this platform")
    assert name not in load_editorial_assets(root, "example")[0]


def test_panel_does_not_equate_import_or_filename_with_approval():
    code = (Path(__file__).parents[2] / "webui" / "rick_editorial_panel.py").read_text(
        encoding="utf-8"
    )
    assert 'import_editorial_material(' in code
    assert 'exclude_editorial_material(' in code
    assert 'restore_editorial_material(' in code
    assert "review_choices = [None, *ranked]" in code
    assert 'st.video(source_path)' in code
    assert 'if review == "Aprovar" and (' in code
    assert 'or not content_checked or not rights_checked' in code
