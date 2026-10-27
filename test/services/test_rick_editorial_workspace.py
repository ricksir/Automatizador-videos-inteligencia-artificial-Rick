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


def test_historical_stock_cache_recovers_only_recorded_files(tmp_path):
    root, folder, materials = _legacy_task(tmp_path)
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    for filename in ("generic.mp4", "portrait.mp4", "election.mp4", "other.mp4"):
        (cache / filename).write_bytes(b"valid dummy bytes")
    # Historical state.materials is empty after a restart; do not silently
    # offer other cached clips from unrelated tasks.
    ws = load_review_workspace(
        root, "task-123", [], audio_duration=4.0, cache_dir=cache
    )
    assert set(ws["paths"]) == {"generic.mp4", "portrait.mp4", "election.mp4"}
    assert "other.mp4" not in ws["paths"]
    original = (folder / "script.json").read_bytes()
    report = save_editorial_workspace_review(
        root, "task-123", ws["preview_sha256"],
        list(ws["paths"].values()), approvals(), audio_duration=4.0,
        cache_dir=cache,
    )
    assert report["status"] == "ready_human_reviewed"
    assert (folder / "script.json").read_bytes() == original


def test_unregistered_or_missing_cached_files_cannot_be_selected(tmp_path):
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    (cache / "other.mp4").write_bytes(b"not from task")
    paths = available_material_paths(
        [{"local_file": "generic.mp4"}, {"local_file": "../other.mp4"}],
        [], cache_dir=cache,
    )
    assert paths == {}
    (cache / "generic.mp4").write_bytes(b"")
    assert available_material_paths(
        [{"local_file": "generic.mp4"}], [], cache_dir=cache
    ) == {}


def test_ambiguous_state_paths_not_overridden_by_cache(tmp_path):
    root, folder, materials = create_task(tmp_path)
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    (cache / "portrait.mp4").write_bytes(b"cache asset")
    duplicate = tmp_path / "another" / "portrait.mp4"
    duplicate.parent.mkdir()
    duplicate.write_bytes(b"conflicting")
    paths = available_material_paths(
        [{"local_file": "portrait.mp4"}],
        [str(folder / "portrait.mp4"), str(duplicate)],
        cache_dir=cache,
    )
    assert paths == {}


def test_symlinked_cache_file_is_not_exposed(tmp_path):
    root, folder, materials = create_task(tmp_path)
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    path = cache / "portrait.mp4"
    try:
        path.symlink_to(folder / "portrait.mp4")
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not permitted on this host")
    assert available_material_paths(
        [{"local_file": "portrait.mp4"}], [], cache_dir=cache
    ) == {}


def test_malformed_cache_name_cannot_escape_cache(tmp_path):
    cache = tmp_path / "cache_videos"
    cache.mkdir()
    external = tmp_path / "private.mp4"
    external.write_bytes(b"private")
    assert available_material_paths(
        [{"local_file": "../private.mp4"}], [], cache_dir=cache
    ) == {}


def test_legacy_missing_state_duration_uses_existing_audio_mp3(tmp_path, monkeypatch):
    root, folder, materials = _legacy_task(tmp_path)
    audio = folder / "audio.mp3"
    audio.write_bytes(b"locally stored audio bytes")
    from app.services import voice

    measured = []
    monkeypatch.setattr(
        voice, "get_audio_duration",
        lambda filename: measured.append(filename) or 4.0,
    )
    original = (folder / "script.json").read_bytes()
    ws = load_review_workspace(root, "task-123", materials)
    assert ws["recovered_preview"] is True
    assert ws["preview"]["scenes"][-1]["end_seconds"] == 4.0
    report = save_editorial_workspace_review(
        root, "task-123", ws["preview_sha256"], materials, approvals()
    )
    assert report["status"] == "ready_human_reviewed"
    assert measured == [str(audio), str(audio)]
    assert (folder / "script.json").read_bytes() == original


def test_legacy_duration_prefers_recorded_measurement_over_audio_mp3(
    tmp_path, monkeypatch
):
    root, folder, materials = _legacy_task(tmp_path)
    (folder / "audio.mp3").write_bytes(b"audio")
    from app.services import voice

    def should_not_measure(*_):
        pytest.fail("Audio must not be decoded when state already has duration")

    monkeypatch.setattr(voice, "get_audio_duration", should_not_measure)
    ws = load_review_workspace(root, "task-123", materials, audio_duration=4.0)
    assert ws["preview"]["scenes"][-1]["end_seconds"] == 4.0


def test_legacy_rejects_empty_audio_mp3_and_does_not_use_final_video(
    tmp_path, monkeypatch
):
    root, folder, materials = _legacy_task(tmp_path)
    (folder / "audio.mp3").write_bytes(b"")
    (folder / "final.mp4").write_bytes(b"not a narration source")
    from app.services import voice

    def should_not_measure(*_):
        pytest.fail("Invalid files must never be probed")

    monkeypatch.setattr(voice, "get_audio_duration", should_not_measure)
    with pytest.raises(ValueError, match="duração medida"):
        load_review_workspace(root, "task-123", materials)


def test_legacy_symlinked_audio_cannot_be_decoded(tmp_path, monkeypatch):
    root, folder, materials = _legacy_task(tmp_path)
    external = tmp_path / "external.mp3"
    external.write_bytes(b"not task audio")
    try:
        (folder / "audio.mp3").symlink_to(external)
    except (NotImplementedError, OSError):
        pytest.skip("Symlinks disabled on this host")
    from app.services import voice

    def should_not_measure(*_):
        pytest.fail("Symlink must be excluded")

    monkeypatch.setattr(voice, "get_audio_duration", should_not_measure)
    with pytest.raises(ValueError, match="duração medida"):
        load_review_workspace(root, "task-123", materials)


def test_editorial_ui_requires_explicit_video_choice_when_unverified():
    text = (Path(__file__).parents[2] / "webui" / "rick_editorial_panel.py").read_text(
        encoding="utf-8"
    )
    # Metadata ranking does not preselect a candidate.
    assert "ranked = order_review_materials(" in text
    assert "review_choices = [None, *ranked]" in text
    assert "index=review_choices.index(selected_default)" in text
    assert 'if old.get("editorial_review") == "approved_by_human"' in text
    assert "if chosen is not None:" in text
    # Only a previously *saved human approval* can prepopulate a clip.
    # Candidates (even highly ranked ones) must start at the None placeholder.
    assert "review_choices = [None, *ranked]" in text
    assert 'old.get("assigned_material_file")' in text
    assert 'if old.get("editorial_review") == "approved_by_human" else None' in text
    assert "if selected_default not in paths:" in text
    assert "selected_default = None" in text
    assert "selected_default = scene.get(\"assigned_material_file\")" not in text
    # Per-task/per-scene v4 key avoids reusing another scene's Streamlit selection.
    assert 'key=f"rick_editorial_material_v4_{selected_id}_{idx}"' in text
    assert "on_change=_clear_scene_evidence" in text
    assert "args=(selected_id, idx)" in text
    # Clip changes clear evidence before a fresh saved approval can be issued.
    assert text.index("chosen = st.selectbox(") < text.index("with st.form(")
    assert "chosen is None or not note.strip()" in text
    assert "or not content_checked or not rights_checked" in text


def test_changing_clip_clears_only_target_scene_and_task(monkeypatch):
    """Streamlit evidence must not leak into other scenes or other tasks."""
    from types import SimpleNamespace
    from webui import rick_editorial_panel as panel

    state = {}
    for task_id in ("task-a", "task-b"):
        for scene_number in (1, 2):
            suffix = f"{task_id}_{scene_number}"
            state[f"rick_editorial_decision_{suffix}"] = "Aprovar"
            state[f"rick_editorial_source_{suffix}"] = "Fonte previamente conferida"
            state[f"rick_editorial_content_{suffix}"] = True
            state[f"rick_editorial_rights_{suffix}"] = True
    unchanged = {
        key: value for key, value in state.items()
        if not key.endswith("task-a_1")
    }
    monkeypatch.setattr(panel, "st", SimpleNamespace(session_state=state))
    panel._clear_scene_evidence("task-a", 1)

    assert state["rick_editorial_decision_task-a_1"] == "Pendente"
    assert state["rick_editorial_source_task-a_1"] == ""
    assert state["rick_editorial_content_task-a_1"] is False
    assert state["rick_editorial_rights_task-a_1"] is False
    for key, value in unchanged.items():
        assert state[key] == value


def test_ranked_metadata_never_creates_human_approval(tmp_path):
    """Even valid ranking and checked boxes cannot approve without clip choice."""
    from app.services.rick_visual_curation import order_review_materials

    root, _, materials = create_task(tmp_path)
    workspace = load_review_workspace(root, "task-123", materials)
    scene = workspace["preview"]["scenes"][0]
    ranked = order_review_materials(
        scene, workspace["source_metadata"], sorted(workspace["paths"])
    )
    assert ranked
    assert [None, *ranked][0] is None

    report = save_editorial_workspace_review(
        root, "task-123", workspace["preview_sha256"], materials,
        [{
            "scene_number": 1, "decision": "approve", "selected_file": None,
            "source_note": "Uma nota de origem não equivale a escolher vídeo",
            "content_checked": True, "rights_checked": True,
        }],
    )
    assert report["status"] == "blocked"
    assert report["human_approved_count"] == 0
    assert report["scenes"][0]["assigned_material_file"] is None
    assert {"scene_number": 1, "code": "file_missing_or_ambiguous"} in report["blockers"]
