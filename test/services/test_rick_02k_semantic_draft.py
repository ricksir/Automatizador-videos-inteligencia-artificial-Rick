"""Rick 02K: local unapproved draft from direct Gemini observations.

All tests offline, no real Gemini, media downloads or publication.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.services.rick_editorial_workspace import load_review_workspace
from app.services.rick_semantic_draft import (
    build_semantic_draft_assignments,
    export_semantic_draft,
    prepare_semantic_draft,
)
from app.services.rick_semantic_remediation import proposal_fingerprint


def _sample(tmp_path):
    tasks_root = tmp_path / "tasks"
    task_dir = tasks_root / "sample"
    task_dir.mkdir(parents=True)
    cache_dir = tmp_path / "trusted_cache"
    cache_dir.mkdir()
    for name in ("original1.mp4", "original2.mp4", "alternative.mp4"):
        (cache_dir / name).write_bytes(b"fake local video")
    (task_dir / "audio.mp3").write_bytes(b"fake audio")
    (task_dir / "final-1.mp4").write_bytes(b"DO-NOT-REPLACE")
    manifest = {
        "script": "Gramsci e ideias.",
        "params": {
            "video_subject": "Gramsci e sociedade",
            "subtitle_enabled": False, "video_clip_duration": 2,
        },
        "rick_scene_candidate_preview": {
            "scene_count": 2, "alignment": "estimated",
            "scenes": [
                {
                    "scene_number": 1, "text": "Gramsci estudou ideias",
                    "start_seconds": 0, "end_seconds": 2,
                    "assigned_material_file": "original1.mp4",
                    "match_status": "term_match_unverified",
                },
                {
                    "scene_number": 2, "text": "A sociedade pode mudar",
                    "start_seconds": 2, "end_seconds": 4,
                    "assigned_material_file": "original2.mp4",
                    "match_status": "term_match_unverified",
                },
            ],
        },
        "material_sources": [
            {
                "local_file": name, "provider": "pixabay",
                "source_page": f"https://pixabay.com/videos/{i}",
                "search_term": "social studies",
            }
            for i, name in enumerate(
                ["original1.mp4", "original2.mp4", "alternative.mp4"], 1
            )
        ],
    }
    (task_dir / "script.json").write_text(
        json.dumps(manifest), encoding="utf-8",
    )
    workspace = load_review_workspace(
        tasks_root, "sample", [], cache_dir=cache_dir,
    )
    proposals = {"scenes": [
        {"scene_number": 1, "text": "Gramsci estudou ideias",
         "primary": "original1.mp4", "metadata_score": 95},
        {"scene_number": 2, "text": "A sociedade pode mudar",
         "primary": "original2.mp4", "metadata_score": 94},
    ]}
    recovery = {
        "version": 1,
        "model": "gemini-test",
        "source_preview_sha256": workspace["preview_sha256"],
        "source_precuration_sha256": proposal_fingerprint(proposals),
        "targets": [1],
        "ranking": [{
            "scene_number": 1,
            "suggested_file": "alternative.mp4",
            "status": "candidato_para_revisao_humana",
            "auto_selection_permitted": False,
            "publishing_permitted": False,
        }],
        "compared": [{
            "scene_number": 1, "file": "alternative.mp4",
            "original_file": "original1.mp4",
            "status": "ai_assessment_for_human_review",
            "verdict": "plausible", "visual_relation": "direct",
            "visible_evidence": "Pessoa consultando livros",
            "source_page": "https://pixabay.com/videos/3",
        }],
    }
    return tasks_root, task_dir, cache_dir, workspace, proposals, {"1": recovery}


def test_direct_gemini_replaces_only_first_scene_with_explicit_unreviewed_fallback(tmp_path):
    _, _, _, workspace, proposals, results = _sample(tmp_path)
    plan = build_semantic_draft_assignments(workspace, proposals, results)
    assert plan["recommended_count"] == 1
    assert plan["fallback_count"] == 1
    assert plan["recommended_scenes"] == [1]
    assert plan["fallback_scenes"] == [2]
    assert [
        row["assigned_material_file"] for row in plan["scenes"]
    ] == ["alternative.mp4", "original2.mp4"]
    assert plan["scenes"][0]["selection_basis"] == (
        "gemini_direct_candidate_not_human_approved"
    )
    assert plan["scenes"][1]["selection_basis"] == "original_metadata_unverified"
    assert not plan["publishing_permitted"]
    assert not plan["human_approved"]


def test_fingerprint_ignores_only_volatile_diagnostics_and_rejects_media_change(tmp_path):
    _, _, _, _, proposals, _ = _sample(tmp_path)
    changed = deepcopy(proposals)
    changed["discovery"] = {"imported_count": 6}
    changed["scenes"][0]["metadata_score"] = 5
    assert proposal_fingerprint(changed) == proposal_fingerprint(proposals)
    changed["scenes"][0]["primary"] = "replacement.mp4"
    assert proposal_fingerprint(changed) != proposal_fingerprint(proposals)


@pytest.mark.parametrize("property_name, value", [
    ("verdict", "uncertain"),
    ("visual_relation", "contextual"),
    ("status", "provider_or_response_failure"),
    ("visible_evidence", ""),
    ("file", "original1.mp4"),
])
def test_untrusted_gemini_candidate_cannot_replace_fallback(
    tmp_path, property_name, value,
):
    _, _, _, workspace, proposals, results = _sample(tmp_path)
    results["1"]["compared"][0][property_name] = value
    with pytest.raises(ValueError, match="evidência direta"):
        build_semantic_draft_assignments(workspace, proposals, results)


def test_no_direct_match_disables_expensive_preview(tmp_path):
    _, _, _, workspace, proposals, results = _sample(tmp_path)
    results["1"]["ranking"][0]["suggested_file"] = None
    with pytest.raises(ValueError, match="Nenhuma alternativa"):
        build_semantic_draft_assignments(workspace, proposals, results)


@pytest.mark.parametrize("change", [
    "source_preview_sha256", "source_precuration_sha256",
])
def test_old_or_different_baseline_cannot_render(tmp_path, change):
    _, _, _, workspace, proposals, results = _sample(tmp_path)
    results["1"][change] = "obsolete"
    with pytest.raises(ValueError, match="Comparações antigas"):
        build_semantic_draft_assignments(workspace, proposals, results)


def test_edited_scene_text_blocks(tmp_path):
    _, _, _, workspace, proposals, results = _sample(tmp_path)
    proposals["scenes"][1]["text"] = "texto diferente"
    with pytest.raises(ValueError, match="pré-curadoria foi modificada"):
        build_semantic_draft_assignments(workspace, proposals, results)


def test_missing_local_media_blocks(tmp_path):
    _, _, cache_dir, workspace, proposals, results = _sample(tmp_path)
    (cache_dir / "original2.mp4").unlink()
    workspace["paths"].pop("original2.mp4", None)
    with pytest.raises(ValueError, match="sem mídia local"):
        build_semantic_draft_assignments(workspace, proposals, results)


def test_source_outside_group_rejected(tmp_path):
    _, _, _, workspace, proposals, results = _sample(tmp_path)
    results["1"]["ranking"][0]["scene_number"] = 2
    with pytest.raises(ValueError, match="fora do grupo"):
        build_semantic_draft_assignments(workspace, proposals, results)


def test_no_missing_subtitles_silent_fallback(tmp_path, monkeypatch):
    root, folder, cache, _, proposals, results = _sample(tmp_path)
    manifest = json.loads((folder / "script.json").read_text(encoding="utf-8"))
    manifest["params"]["subtitle_enabled"] = True
    (folder / "script.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(
        "app.services.rick_semantic_draft.voice.get_audio_duration",
        lambda _: 4.0,
    )
    with pytest.raises(ValueError, match="subtitle.srt"):
        prepare_semantic_draft(
            root, "sample", state_materials=[], cache_dir=cache,
            original_proposals=proposals, recovery_history=results,
        )
    plan = prepare_semantic_draft(
        root, "sample", state_materials=[], cache_dir=cache,
        original_proposals=proposals, recovery_history=results,
        without_subtitles=True,
    )
    assert plan["subtitle"] == ""


def test_audio_mismatch_fails_before_render(tmp_path, monkeypatch):
    root, _, cache, _, proposals, results = _sample(tmp_path)
    monkeypatch.setattr(
        "app.services.rick_semantic_draft.voice.get_audio_duration",
        lambda _: 9.0,
    )
    with pytest.raises(ValueError, match="duração"):
        prepare_semantic_draft(
            root, "sample", state_materials=[], cache_dir=cache,
            original_proposals=proposals, recovery_history=results,
        )


def test_local_mp4_mock_keeps_original_state_and_reports_all_fallbacks(
    tmp_path, monkeypatch,
):
    root, folder, cache, _, proposals, results = _sample(tmp_path)
    original_proposals = deepcopy(proposals)
    recovery_snapshot = deepcopy(results)
    monkeypatch.setattr(
        "app.services.rick_semantic_draft.voice.get_audio_duration",
        lambda _: 4.0,
    )
    observed = []
    def fake_combine(**kwargs):
        observed.append(kwargs)
        assert kwargs["scene_timeline"]["scene_count"] == 2
        assert [s["source_file"] for s in kwargs["scene_timeline"]["segments"]] == [
            "alternative.mp4", "original2.mp4",
        ]
        Path(kwargs["combined_video_path"]).write_bytes(b"intermediate")
        kwargs["used_video_paths"].extend(kwargs["video_paths"])
    def fake_finalize(**kwargs):
        assert kwargs["bgm_file_override"] == ""
        Path(kwargs["output_file"]).write_bytes(b"preview")
    monkeypatch.setattr(
        "app.services.rick_semantic_draft.video.combine_videos", fake_combine,
    )
    monkeypatch.setattr(
        "app.services.rick_semantic_draft.video.generate_video", fake_finalize,
    )
    out = export_semantic_draft(
        root, "sample", state_materials=[], cache_dir=cache,
        original_proposals=proposals, recovery_history=results,
    )
    assert len(observed) == 1
    assert Path(out["output"]).read_bytes() == b"preview"
    assert Path(out["report"]).is_file()
    report = json.loads(Path(out["report"]).read_text(encoding="utf-8"))
    assert report["status"] == "draft_machine_suggested_not_human_approved"
    assert report["fallback_count"] == 1
    assert report["human_approved"] is False
    assert report["rights_legally_verified"] is False
    assert report["publishing_permitted"] is False
    assert report["background_music_reused"] is False
    assert report["scene_assignments"][1]["selection_basis"] == "original_metadata_unverified"
    assert report["used_source_basenames"] == [
        "alternative.mp4", "original2.mp4",
    ]
    assert (folder / "final-1.mp4").read_bytes() == b"DO-NOT-REPLACE"
    assert not (folder / "rick_editorial_review.json").exists()
    assert proposals == original_proposals and results == recovery_snapshot


def test_still_no_draft_without_a_completed_comparison(tmp_path):
    _, _, _, ws, proposals, _ = _sample(tmp_path)
    with pytest.raises(ValueError, match="incompatíveis"):
        build_semantic_draft_assignments(ws, proposals, {})


def test_ui_exposes_only_opt_in_draft_with_original_preserved():
    code = (Path(__file__).parents[2] / "webui" / "rick_editorial_panel.py").read_text(
        encoding="utf-8",
    )
    assert "Rick — Montar prévia semântica em MP4 (rascunho)" in code
    assert "Gerar MP4 de prévia semântica" in code
    assert "disabled=not confirmed_draft" in code
    assert "recovery_history=history" in code
    assert "Não publique esta prévia." in code
