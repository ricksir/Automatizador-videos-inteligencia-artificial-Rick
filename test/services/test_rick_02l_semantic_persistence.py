"""Offline security and resume regression tests for Gemini batch persistence."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.services.rick_editorial_workspace import load_review_workspace
from app.services.rick_semantic_remediation import proposal_fingerprint
from app.services.rick_semantic_draft import build_semantic_draft_assignments
from app.services.rick_semantic_session_store import (
    load_semantic_batch,
    record_semantic_assessment,
    record_semantic_failed_retry,
    record_semantic_recovery,
)


def _fixture(tmp_path):
    tasks_root = tmp_path / "tasks"
    task_dir = tasks_root / "t123"
    task_dir.mkdir(parents=True)
    cache = tmp_path / "trusted_cache"
    cache.mkdir()
    for name in ("original1.mp4", "original2.mp4", "alternative.mp4"):
        (cache / name).write_bytes(b"synthetic local file")
    preview = {
        "version": 1, "scene_count": 2,
        "scenes": [
            {"scene_number": 1, "text": "Gramsci estudou ideias",
             "start_seconds": 0, "end_seconds": 2,
             "assigned_material_file": "original1.mp4",
             "match_status": "term_match_unverified"},
            {"scene_number": 2, "text": "Grupos podem mudar a sociedade",
             "start_seconds": 2, "end_seconds": 4,
             "assigned_material_file": "original2.mp4",
             "match_status": "term_match_unverified"},
        ],
    }
    source_records = [
        {"local_file": name, "provider": "pixabay",
         "search_term": "Gramsci"}
        for name in ("original1.mp4", "original2.mp4", "alternative.mp4")
    ]
    (task_dir / "script.json").write_text(
        json.dumps({
            "script": "Gramsci estudou ideias. Grupos podem mudar a sociedade.",
            "material_sources": source_records,
            "rick_scene_candidate_preview": preview,
        }), encoding="utf-8",
    )
    ws = load_review_workspace(tasks_root, "t123", [], cache_dir=cache)
    precure = {"scenes": [
        {"scene_number": 1, "text": "Gramsci estudou ideias",
         "primary": "original1.mp4"},
        {"scene_number": 2, "text": "Grupos podem mudar a sociedade",
         "primary": "original2.mp4"},
    ]}
    assessment = {
        "version": 2, "provider": "gemini", "model": "gemini-test",
        "assessed": 2, "attempted": 2, "api_requests": 2,
        "rights_verified": False, "publishing_permitted": False,
        "results": [
            {"scene_number": number, "file": f"original{number}.mp4",
             "verdict": "uncertain", "visual_relation": "contextual",
             "status": "ai_assessment_for_human_review",
             "visible_evidence": "Foto de grupo", "reason": "Tema contextual",
             "recommended_action": "inspecionar_e_buscar_alternativa"}
            for number in (1, 2)
        ],
    }
    recovery = {
        "version": 1, "model": "gemini-test",
        "source_preview_sha256": ws["preview_sha256"],
        "source_precuration_sha256": proposal_fingerprint(precure),
        "targets": [1], "api_requests": 1, "ai_assessed": 1,
        "max_candidates_per_scene": 2, "human_approved": False,
        "publishing_permitted": False, "original_proposals_unchanged": True,
        "discovery": {"imported_count": 1},
        "compared": [{
            "scene_number": 1, "file": "alternative.mp4",
            "original_file": "original1.mp4",
            "status": "ai_assessment_for_human_review",
            "verdict": "plausible", "visual_relation": "direct",
            "visible_evidence": "Alguém lendo um livro",
            "metadata_score": 90, "source_page": "https://example.org/candidate",
        }],
        "ranking": [{
            "scene_number": 1, "candidates_examined": 1,
            "direct_candidates": 1, "suggested_file": "alternative.mp4",
            "status": "candidato_para_revisao_humana",
            "auto_selection_permitted": False,
            "publishing_permitted": False,
        }],
        "unresolved": [],
    }
    kwargs = {
        "first_scene": 1, "workspace": ws, "proposals": precure,
        "model": "gemini-test",
    }
    return tasks_root, task_dir, cache, kwargs, assessment, recovery


def _save_base(root, kwargs, assessment):
    record_semantic_assessment(root, "t123", **kwargs, assessment=assessment)


def _load(root, kwargs):
    return load_semantic_batch(root, "t123", **kwargs)


def _recover(root, kwargs, result):
    return record_semantic_recovery(root, "t123", **kwargs, recovery=result)



def test_retry_of_failed_scene_preserves_unaffected_recovery_and_restarts(tmp_path):
    root, _, _, kwargs, assessment, recovery = _fixture(tmp_path)
    assessment["results"][1].update({
        "status": "provider_or_response_failure",
        "failure_stage": "api_request",
        "failure_kind": "quota_or_rate_limit",
        "verdict": "uncertain", "visual_relation": "insufficient",
        "visible_evidence": "", "reason": "",
    })
    assessment["assessed"] = 1
    _save_base(root, kwargs, assessment)
    _recover(root, kwargs, recovery)
    retry = deepcopy(assessment)
    retry["results"][1].update({
        "status": "ai_assessment_for_human_review",
        "verdict": "uncertain", "visual_relation": "contextual",
        "visible_evidence": "Foto de grupo", "reason": "Tema contextual",
    })
    retry["results"][1].pop("failure_stage", None)
    retry["results"][1].pop("failure_kind", None)
    retry["assessed"] = 2
    retry["api_requests"] = 3
    updated = record_semantic_failed_retry(
        root, "t123", **kwargs, assessment=retry,
    )
    assert set(updated["history"]) == {"1"}
    assert updated["assessment"]["assessed"] == 2
    reopened = _load(root, kwargs)
    assert reopened["history"]["1"]["ranking"][0]["suggested_file"] == "alternative.mp4"
    assert reopened["assessment"]["results"][1]["status"] == "ai_assessment_for_human_review"
    assert reopened["assessment"]["api_requests"] == 3
    assert reopened["assessment"]["publishing_permitted"] is False


def test_failed_retry_cannot_mutate_a_completed_scene_or_erase_history(tmp_path):
    root, folder, _, kwargs, assessment, recovery = _fixture(tmp_path)
    assessment["results"][1].update({
        "status": "provider_or_response_failure",
        "failure_stage": "api_request",
        "verdict": "uncertain", "visual_relation": "insufficient",
        "visible_evidence": "", "reason": "",
    })
    assessment["assessed"] = 1
    _save_base(root, kwargs, assessment)
    _recover(root, kwargs, recovery)
    path = folder / "rick_semantic_batch_01.json"
    existing = path.read_bytes()
    retry = deepcopy(assessment)
    retry["results"][0]["visible_evidence"] = "Outras imagens não revisadas"
    retry["api_requests"] = 3
    with pytest.raises(ValueError, match="parecer válido"):
        record_semantic_failed_retry(root, "t123", **kwargs, assessment=retry)
    assert path.read_bytes() == existing
    retry["results"][0] = deepcopy(assessment["results"][0])
    retry["results"][1]["file"] = "alternative.mp4"
    with pytest.raises(ValueError, match="mídia"):
        record_semantic_failed_retry(root, "t123", **kwargs, assessment=retry)
    assert path.read_bytes() == existing


def test_retry_without_saved_baseline_is_blocked(tmp_path):
    root, _, _, kwargs, assessment, _ = _fixture(tmp_path)
    with pytest.raises(ValueError, match="persistida"):
        record_semantic_failed_retry(
            root, "t123", **kwargs, assessment=assessment
        )


def test_retry_ui_keeps_existing_groups_and_skips_processed_scenes():
    code = (
        Path(__file__).parents[2] / "webui" / "rick_editorial_panel.py"
    ).read_text(encoding="utf-8")
    assert "record_semantic_failed_retry(" in code
    assert 'st.session_state[history_key] = persisted["history"]' in code
    assert "processed_scenes = {" in code
    assert "if number not in processed_scenes" in code
    assert "recovery_groups = [*processed_groups, *pending_groups]" in code



def test_round_trip_reopens_both_analysis_and_alternatives(tmp_path):
    root, folder, _, kwargs, assessment, recovery = _fixture(tmp_path)
    assert _load(root, kwargs) == {"assessment": None, "history": {}}
    _save_base(root, kwargs, assessment)
    restored = _load(root, kwargs)
    assert restored["assessment"]["results"][0]["file"] == "original1.mp4"
    assert restored["history"] == {}
    _recover(root, kwargs, recovery)
    reopened = _load(root, kwargs)
    assert reopened["history"]["1"]["ranking"][0]["suggested_file"] == "alternative.mp4"
    assert reopened["history"]["1"]["compared"][0]["visual_relation"] == "direct"
    assert reopened["history"]["1"]["discovery"]["imported_count"] == 1
    assert (folder / "rick_semantic_batch_01.json").is_file()


def test_restored_evidence_can_build_safe_semantic_mp4_draft(tmp_path):
    root, _, _, kwargs, assessment, recovery = _fixture(tmp_path)
    _save_base(root, kwargs, assessment)
    _recover(root, kwargs, recovery)
    restored = _load(root, kwargs)
    draft = build_semantic_draft_assignments(
        kwargs["workspace"], kwargs["proposals"], restored["history"],
    )
    assert draft["recommended_scenes"] == [1]
    assert draft["fallback_scenes"] == [2]
    assert [
        row["assigned_material_file"] for row in draft["scenes"]
    ] == ["alternative.mp4", "original2.mp4"]
    assert draft["publishing_permitted"] is False


def test_only_whitelisted_evidence_is_saved_without_credential(tmp_path):
    root, folder, _, kwargs, assessment, recovery = _fixture(tmp_path)
    assessment["api_key"] = "SECRET_API_KEY_SHOULD_NOT_BE_SAVED"
    assessment["results"][0]["image_b64"] = "SECRET_RAW_IMAGE"
    recovery["gemini_api_key"] = "SECRET_RECOVERY_KEY"
    recovery["compared"][0]["local_path"] = "C:/Users/private/Downloads/key"
    recovery["compared"][0]["failure_kind"] = "SECRET_FAILURE_KIND_FROM_COMPARISON"
    _save_base(root, kwargs, assessment)
    _recover(root, kwargs, recovery)
    raw = (folder / "rick_semantic_batch_01.json").read_text(encoding="utf-8")
    for secret in (
        "SECRET_API_KEY_SHOULD_NOT_BE_SAVED", "SECRET_RAW_IMAGE",
        "SECRET_RECOVERY_KEY", "C:/Users/private/Downloads/key",
        "SECRET_FAILURE_KIND_FROM_COMPARISON",
    ):
        assert secret not in raw
    assert '"publishing_permitted":false' in raw


def test_repeated_click_is_blocked_without_mutating_previous_result(tmp_path):
    root, folder, _, kwargs, assessment, recovery = _fixture(tmp_path)
    _save_base(root, kwargs, assessment)
    _recover(root, kwargs, recovery)
    previous = (folder / "rick_semantic_batch_01.json").read_bytes()
    with pytest.raises(ValueError, match="já tiveram"):
        _recover(root, kwargs, recovery)
    assert (folder / "rick_semantic_batch_01.json").read_bytes() == previous


def test_second_group_survives_restart_without_replacing_first(tmp_path):
    root, _, _, kwargs, assessment, recovery = _fixture(tmp_path)
    _save_base(root, kwargs, assessment)
    _recover(root, kwargs, recovery)
    second = deepcopy(recovery)
    second["targets"] = [2]
    second["compared"][0].update({
        "scene_number": 2, "original_file": "original2.mp4",
    })
    second["ranking"][0]["scene_number"] = 2
    _recover(root, kwargs, second)
    assert set(_load(root, kwargs)["history"]) == {"1", "2"}
    assert _load(root, kwargs)["history"]["1"]["ranking"][0]["suggested_file"] == "alternative.mp4"


def test_overlapping_groups_cannot_reuse_a_paid_scene(tmp_path):
    root, _, _, kwargs, assessment, recovery = _fixture(tmp_path)
    _save_base(root, kwargs, assessment)
    _recover(root, kwargs, recovery)
    overlap = deepcopy(recovery)
    overlap["targets"] = [1, 2]
    with pytest.raises(ValueError, match="já tiveram"):
        _recover(root, kwargs, overlap)


def test_new_assessment_clears_old_groups(tmp_path):
    root, _, _, kwargs, assessment, recovery = _fixture(tmp_path)
    _save_base(root, kwargs, assessment)
    _recover(root, kwargs, recovery)
    changed = deepcopy(assessment)
    changed["results"][0]["visible_evidence"] = "Outra observação"
    _save_base(root, kwargs, changed)
    assert _load(root, kwargs)["history"] == {}
    assert _load(root, kwargs)["assessment"]["results"][0]["visible_evidence"] == "Outra observação"


def test_other_model_and_other_primary_are_not_reused(tmp_path):
    root, _, _, kwargs, assessment, recovery = _fixture(tmp_path)
    _save_base(root, kwargs, assessment)
    _recover(root, kwargs, recovery)
    assert _load(root, {**kwargs, "model": "new-model"})["assessment"] is None
    revised = deepcopy(kwargs["proposals"])
    revised["scenes"][0]["primary"] = "alternative.mp4"
    assert _load(root, {**kwargs, "proposals": revised})["assessment"] is None


def test_different_preview_is_not_reused(tmp_path):
    root, _, _, kwargs, assessment, recovery = _fixture(tmp_path)
    _save_base(root, kwargs, assessment)
    _recover(root, kwargs, recovery)
    changed = {**kwargs["workspace"], "preview_sha256": "f" * 64}
    assert _load(root, {**kwargs, "workspace": changed})["assessment"] is None


def test_local_candidate_removed_discards_only_stale_recovery(tmp_path):
    root, _, cache, kwargs, assessment, recovery = _fixture(tmp_path)
    _save_base(root, kwargs, assessment)
    _recover(root, kwargs, recovery)
    (cache / "alternative.mp4").unlink()
    newws = load_review_workspace(root, "t123", [], cache_dir=cache)
    restored = _load(root, {**kwargs, "workspace": newws})
    assert restored["assessment"]["results"]
    assert restored["history"] == {}


def test_corrupt_oversized_and_symlinked_history_are_ignored(tmp_path):
    root, folder, _, kwargs, assessment, _ = _fixture(tmp_path)
    _save_base(root, kwargs, assessment)
    path = folder / "rick_semantic_batch_01.json"
    path.write_text("{not-json", encoding="utf-8")
    assert _load(root, kwargs)["assessment"] is None
    path.write_bytes(b"x" * (512 * 1024 + 1))
    assert _load(root, kwargs)["assessment"] is None
    path.unlink()
    target = tmp_path / "outside.json"
    target.write_text(json.dumps({"api_key": "outside"}), encoding="utf-8")
    try:
        path.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("System does not permit creating symlinks")
    assert _load(root, kwargs)["assessment"] is None
    with pytest.raises(ValueError, match="não autorizado"):
        _save_base(root, kwargs, assessment)


def test_missing_original_media_invalidates_entire_assessment(tmp_path):
    root, _, cache, kwargs, assessment, _ = _fixture(tmp_path)
    _save_base(root, kwargs, assessment)
    (cache / "original1.mp4").unlink()
    updated_ws = load_review_workspace(root, "t123", [], cache_dir=cache)
    assert _load(
        root, {**kwargs, "workspace": updated_ws}
    ) == {"assessment": None, "history": {}}


def test_corrupted_row_schema_is_not_loaded_into_streamlit(tmp_path):
    root, folder, _, kwargs, assessment, recovery = _fixture(tmp_path)
    _save_base(root, kwargs, assessment)
    _recover(root, kwargs, recovery)
    path = folder / "rick_semantic_batch_01.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["assessment"]["results"][0]["status"] = ["not-a-string"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert _load(root, kwargs)["assessment"] is None

    _save_base(root, kwargs, assessment)
    _recover(root, kwargs, recovery)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["history"]["1"]["ranking"][0]["suggested_file"] = ["bad-list"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    restored = _load(root, kwargs)
    assert restored["assessment"] is not None
    assert restored["history"] == {}


def test_persisted_record_cannot_claim_human_approval_or_publication(tmp_path):
    root, folder, _, kwargs, assessment, recovery = _fixture(tmp_path)
    _save_base(root, kwargs, assessment)
    _recover(root, kwargs, recovery)
    path = folder / "rick_semantic_batch_01.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["history"]["1"]["ranking"][0]["publishing_permitted"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    restored = _load(root, kwargs)
    assert restored["assessment"] is not None
    assert restored["history"] == {}

    payload["history"] = {}
    payload["assessment"]["human_approved"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert _load(root, kwargs) == {"assessment": None, "history": {}}


def test_recovery_cannot_be_recorded_without_assessment(tmp_path):
    root, _, _, kwargs, _, recovery = _fixture(tmp_path)
    with pytest.raises(ValueError, match="Salve primeiro"):
        _recover(root, kwargs, recovery)


def test_provider_failure_stays_failure_after_restart(tmp_path):
    root, _, _, kwargs, assessment, _ = _fixture(tmp_path)
    assessment["results"][0].update({
        "status": "provider_or_response_failure",
        "failure_stage": "api_request",
        "failure_kind": "quota_or_rate_limit",
        "verdict": "uncertain", "visual_relation": "insufficient",
    })
    _save_base(root, kwargs, assessment)
    restored = _load(root, kwargs)
    assert restored["assessment"]["results"][0]["status"] == "provider_or_response_failure"
    assert restored["assessment"]["results"][0]["failure_stage"] == "api_request"
    assert restored["assessment"]["results"][0]["failure_kind"] == "quota_or_rate_limit"


def test_invalid_gemini_failure_kind_is_never_stored(tmp_path):
    root, folder, _, kwargs, assessment, _ = _fixture(tmp_path)
    assessment["results"][0].update({
        "status": "provider_or_response_failure",
        "failure_stage": "api_request",
        "failure_kind": "SECRET_UNTRUSTED_PROVIDER_MESSAGE",
        "verdict": "uncertain", "visual_relation": "insufficient",
    })
    with pytest.raises(ValueError, match="não corresponde"):
        _save_base(root, kwargs, assessment)
    assert not (folder / "rick_semantic_batch_01.json").exists()


def test_old_error_without_category_remains_restorable(tmp_path):
    root, _, _, kwargs, assessment, _ = _fixture(tmp_path)
    assessment["results"][0].update({
        "status": "provider_or_response_failure",
        "failure_stage": "api_request",
        "verdict": "uncertain", "visual_relation": "insufficient",
    })
    _save_base(root, kwargs, assessment)
    row = _load(root, kwargs)["assessment"]["results"][0]
    assert row["failure_stage"] == "api_request"
    assert "failure_kind" not in row


def test_invalid_and_duplicate_assessment_rows_refused(tmp_path):
    root, _, _, kwargs, assessment, _ = _fixture(tmp_path)
    assessment["results"][1]["scene_number"] = 1
    with pytest.raises(ValueError, match="não corresponde"):
        _save_base(root, kwargs, assessment)


def test_ui_restores_without_network_and_updates_store_on_click():
    text = (Path(__file__).parents[2] / "webui"
            / "rick_editorial_panel.py").read_text(encoding="utf-8")
    assert "load_semantic_batch(" in text
    assert "record_semantic_assessment(" in text
    assert "record_semantic_recovery(" in text
    assert "restaurados do armazenamento" in text
    assert "st.session_state[history_key] = (" in text
