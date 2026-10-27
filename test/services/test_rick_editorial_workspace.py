"""Offline tests for the local editorial workspace; no API keys, network or FFmpeg."""
import json
from pathlib import Path

import pytest

from app.services.rick_editorial_workspace import (
    available_material_paths,
    load_review_workspace,
    save_editorial_workspace_review,
    task_folder,
)


def create_task(tmp_path):
    root = tmp_path / "tasks"
    folder = root / "task-123"
    folder.mkdir(parents=True)
    preview = {
        "status": "preview_only_not_rendered",
        "alignment": "estimated",
        "scene_count": 2,
        "scenes": [
            {
                "start_seconds": 0,
                "end_seconds": 2,
                "text": "Gramsci",
                "search_term": "Gramsci",
                "assigned_material_file": "generic.mp4",
                "match_status": "term_match_unverified",
            },
            {
                "start_seconds": 2,
                "end_seconds": 4,
                "text": "Uma eleição",
                "search_term": "election",
                "assigned_material_file": "election.mp4",
                "match_status": "term_match_unverified",
            },
        ],
    }
    manifest = {
        "script": "Gramsci. Uma eleição.",
        "rick_scene_candidate_preview": preview,
        "material_sources": [
            {"local_file": name, "search_term": name}
            for name in ("generic.mp4", "portrait.mp4", "election.mp4")
        ],
    }
    (folder / "script.json").write_text(json.dumps(manifest), encoding="utf-8")
    videos = []
    for name in ("generic.mp4", "portrait.mp4", "election.mp4"):
        p = folder / name
        p.write_bytes(b"video stub for local file existence only")
        videos.append(str(p))
    return root, folder, videos


def approvals():
    return [
        {
            "scene_number": 1, "decision": "approve",
            "selected_file": "portrait.mp4",
            "source_note": "Arquivo de retrato e direitos revisados manualmente",
            "content_checked": True, "rights_checked": True,
        },
        {
            "scene_number": 2, "decision": "approve",
            "selected_file": "election.mp4",
            "source_note": "Fonte conferida manualmente",
            "content_checked": True, "rights_checked": True,
        },
    ]


def test_local_editorial_review_stays_in_separate_artifact(tmp_path):
    root, folder, materials = create_task(tmp_path)
    original_script = (folder / "script.json").read_bytes()
    workspace = load_review_workspace(root, "task-123", materials)
    assert set(workspace["paths"]) == {"generic.mp4", "portrait.mp4", "election.mp4"}
    assert workspace["saved_review"] is None
    report = save_editorial_workspace_review(
        root, "task-123", workspace["preview_sha256"], materials, approvals()
    )
    assert report["status"] == "ready_human_reviewed"
    assert report["scenes"][0]["assigned_material_file"] == "portrait.mp4"
    assert (folder / "script.json").read_bytes() == original_script
    document = json.loads((folder / "rick_editorial_review.json").read_text(encoding="utf-8"))
    assert document["review"]["status"] == "ready_human_reviewed"
    assert load_review_workspace(root, "task-123", materials)["saved_review"]["human_approved_count"] == 2


def test_partial_review_saved_only_as_blocked_draft(tmp_path):
    root, folder, materials = create_task(tmp_path)
    workspace = load_review_workspace(root, "task-123", materials)
    report = save_editorial_workspace_review(
        root, "task-123", workspace["preview_sha256"], materials, approvals()[:1]
    )
    assert report["status"] == "blocked"
    assert report["scenes"][1]["assigned_material_file"] is None


def test_preview_changed_between_view_and_submit_fails_closed(tmp_path):
    root, folder, materials = create_task(tmp_path)
    workspace = load_review_workspace(root, "task-123", materials)
    manifest = json.loads((folder / "script.json").read_text(encoding="utf-8"))
    manifest["rick_scene_candidate_preview"]["scenes"][0]["text"] = "Outro assunto"
    (folder / "script.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="alterada"):
        save_editorial_workspace_review(
            root, "task-123", workspace["preview_sha256"], materials, approvals()
        )


def test_missing_preview_does_not_fabricate_review(tmp_path):
    root, folder, materials = create_task(tmp_path)
    (folder / "script.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="prévia"):
        load_review_workspace(root, "task-123", materials)


def test_only_valid_manifest_files_are_available(tmp_path):
    root, folder, materials = create_task(tmp_path)
    choices = available_material_paths(
        [{"local_file": "portrait.mp4"}, {"local_file": "../secret.mp4"}],
        materials + [str(folder / "secret.mp4")],
    )
    assert set(choices) == {"portrait.mp4"}


def test_ambiguous_basenames_are_excluded(tmp_path):
    root, folder, materials = create_task(tmp_path)
    other = tmp_path / "other" / "portrait.mp4"
    other.parent.mkdir()
    other.write_bytes(b"video")
    paths = available_material_paths(
        [{"local_file": "portrait.mp4"}],
        [str(folder / "portrait.mp4"), str(other)],
    )
    assert "portrait.mp4" not in paths


def test_missing_video_is_not_selectable(tmp_path):
    root, folder, materials = create_task(tmp_path)
    Path(materials[1]).unlink()
    paths = available_material_paths([{"local_file": "portrait.mp4"}], materials)
    assert paths == {}


def test_reject_traversal_and_invalid_task_ids(tmp_path):
    root, folder, materials = create_task(tmp_path)
    for task_id in ["../task-123", "task-123/../../", ".", "space bad", ""]:
        with pytest.raises(ValueError):
            task_folder(root, task_id)


def test_invalid_or_absent_task_fails_closed(tmp_path):
    root, folder, materials = create_task(tmp_path)
    with pytest.raises(ValueError):
        task_folder(root, "unknown")


def test_missing_manifest_or_bad_json_rejected(tmp_path):
    root, folder, materials = create_task(tmp_path)
    (folder / "script.json").write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="prévia"):
        load_review_workspace(root, "task-123", materials)


def test_refuse_task_directory_symlink(tmp_path):
    root, folder, materials = create_task(tmp_path)
    link = root / "task-456"
    try:
        link.symlink_to(folder, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("Symlinks disabled on this Windows installation")
    with pytest.raises(ValueError):
        task_folder(root, "task-456")


def test_form_does_not_call_generation_or_paid_services():
    source = (Path(__file__).parents[2] / "webui" / "rick_editorial_panel.py").read_text(
        encoding="utf-8"
    )
    assert "render_editorial_panel" in source
    assert "save_editorial_workspace_review" in source
    assert "generate_final_videos(" not in source
    assert "material.download_videos(" not in source
    assert "voice.tts(" not in source
    assert "upload_post" not in source


def _legacy_task(tmp_path):
    root, folder, materials = create_task(tmp_path)
    manifest = json.loads((folder / "script.json").read_text(encoding="utf-8"))
    del manifest["rick_scene_candidate_preview"]
    manifest["search_terms"] = "generic.mp4, election.mp4"
    manifest["params"] = {
        "video_source": "pixabay",
        "video_clip_duration": 2,
    }
    (folder / "script.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return root, folder, materials


def test_legacy_task_can_be_reviewed_without_generating_video(tmp_path):
    root, folder, materials = _legacy_task(tmp_path)
    original_script_json = (folder / "script.json").read_bytes()
    ws = load_review_workspace(root, "task-123", materials, audio_duration=4.0)
    assert ws["recovered_preview"] is True
    assert ws["preview"]["recovered_from_historical_records"] is True
    assert ws["preview"]["scene_count"] == 2
    assert [s["assigned_material_file"] for s in ws["preview"]["scenes"]] == [
        "generic.mp4", "election.mp4"
    ]
    report = save_editorial_workspace_review(
        root, "task-123", ws["preview_sha256"], materials, approvals(),
        audio_duration=4.0
    )
    assert report["status"] == "ready_human_reviewed"
    assert (folder / "script.json").read_bytes() == original_script_json
    assert load_review_workspace(
        root, "task-123", materials, audio_duration=4.0
    )["saved_review"]["human_approved_count"] == 2


def test_legacy_task_without_duration_rejects_recovery(tmp_path):
    root, _, materials = _legacy_task(tmp_path)
    with pytest.raises(ValueError, match="duração medida"):
        load_review_workspace(root, "task-123", materials)


def test_legacy_task_without_material_provenance_rejects_recovery(tmp_path):
    root, folder, materials = _legacy_task(tmp_path)
    manifest = json.loads((folder / "script.json").read_text(encoding="utf-8"))
    manifest.pop("material_sources")
    (folder / "script.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="sem materiais"):
        load_review_workspace(root, "task-123", materials, audio_duration=4)


def test_legacy_changed_sources_invalidate_review_before_write(tmp_path):
    root, folder, materials = _legacy_task(tmp_path)
    ws = load_review_workspace(root, "task-123", materials, audio_duration=4)
    manifest = json.loads((folder / "script.json").read_text(encoding="utf-8"))
    manifest["material_sources"][0]["search_term"] = "outro material"
    (folder / "script.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="alterada"):
        save_editorial_workspace_review(
            root, "task-123", ws["preview_sha256"], materials, approvals(),
            audio_duration=4
        )
    assert not (folder / "rick_editorial_review.json").exists()


def test_legacy_disallows_source_outside_video_banks(tmp_path):
    root, folder, materials = _legacy_task(tmp_path)
    manifest = json.loads((folder / "script.json").read_text(encoding="utf-8"))
    manifest["params"]["video_source"] = "local"
    (folder / "script.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="banco"):
        load_review_workspace(root, "task-123", materials, audio_duration=4)


def test_existing_preview_keeps_its_original_origin(tmp_path):
    root, folder, materials = create_task(tmp_path)
    ws = load_review_workspace(root, "task-123", materials, audio_duration=None)
    assert ws["recovered_preview"] is False
    assert "recovered_from_historical_records" not in ws["preview"]
