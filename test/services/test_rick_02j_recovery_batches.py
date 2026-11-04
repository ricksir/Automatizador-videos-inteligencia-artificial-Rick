"""Recovery group selection and no-repeat routing, all offline.

The UI must not silently reprocess scenes 1-3 when 4-6 remain.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from app.services import rick_semantic_remediation as recovery


def _fixtures(tmp_path):
    scene_texts = [
        "Gramsci estudou ideias", "a sociedade e como",
        "grupos podem mudar isso sem", "precisar de violência.",
        "Ele chamou isso de luta", "de posições e confronto",
    ]
    proposals = {"scenes": [
        {"scene_number": i, "text": text, "primary": f"original-{i}.mp4"}
        for i, text in enumerate(scene_texts, 1)
    ]}
    semantic = {
        "version": 2,
        "model": "gemini-test",
        "results": [
            {
                "scene_number": i, "file": f"original-{i}.mp4",
                "status": "ai_assessment_for_human_review",
                "verdict": "uncertain", "visual_relation": "contextual",
            }
            for i in range(1, 7)
        ],
    }
    workspace = {
        "preview": {"scenes": [{"text": t} for t in scene_texts]},
        "preview_sha256": "stable-mock-preview-fingerprint",
        "source_metadata": {},
        "paths": {},
        "saved_review": {"scenes": [
            {"editorial_review": "unreviewed"} for _ in scene_texts
        ]},
    }
    return proposals, semantic, workspace


def _run(tmp_path, monkeypatch, *, targets=None, report=None):
    proposals, semantic, workspace = _fixtures(tmp_path)
    if report is not None:
        semantic = report
    load_count = []
    monkeypatch.setattr(
        recovery, "load_review_workspace",
        lambda *a, **kw: load_count.append(True) or workspace,
    )
    monkeypatch.setattr(
        recovery, "review_scene_frames",
        lambda *a, **kw: pytest.fail("No candidates: no Gemini calls"),
    )
    before = deepcopy(proposals)
    result = recovery.run_semantic_remediation(
        tmp_path, "task", [],
        original_proposals=proposals,
        semantic_assessment=semantic,
        subject="Gramsci", api_key="fake-key",
        model="gemini-test", consent=True,
        discover=False, max_scenes=3,
        target_scene_numbers=targets,
    )
    assert proposals == before
    assert result["api_requests"] == 0
    assert not result["compared"]
    assert not result["publishing_permitted"]
    assert not result["human_approved"]
    return result


def test_default_legacy_route_is_first_three(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch)
    assert result["targets"] == [1, 2, 3]
    assert [x["scene_number"] for x in result["unresolved"]] == [1, 2, 3]


def test_second_click_can_explicitly_route_to_remaining_three(
    tmp_path, monkeypatch,
):
    result = _run(tmp_path, monkeypatch, targets=[4, 5, 6])
    assert result["targets"] == [4, 5, 6]
    assert [x["scene_number"] for x in result["unresolved"]] == [4, 5, 6]


def test_route_specific_subgroup_and_preserve_given_order(
    tmp_path, monkeypatch,
):
    result = _run(tmp_path, monkeypatch, targets=[6, 4])
    assert result["targets"] == [6, 4]
    assert [x["scene_number"] for x in result["unresolved"]] == [6, 4]


@pytest.mark.parametrize("bad_targets", [
    [], [1, 1], [1, 2, 3, 4], [0], [61], [True], ["1"], "1,2,3",
])
def test_rejects_invalid_target_list_without_files_or_api(
    tmp_path, monkeypatch, bad_targets,
):
    proposals, semantic, workspace = _fixtures(tmp_path)
    monkeypatch.setattr(
        recovery, "load_review_workspace",
        lambda *a, **kw: pytest.fail("Do not read workspace on invalid input"),
    )
    with pytest.raises(ValueError, match="inválidos"):
        recovery.run_semantic_remediation(
            tmp_path, "task", [],
            original_proposals=proposals,
            semantic_assessment=semantic,
            subject="Gramsci", api_key="fake-key",
            model="gemini-test", consent=True,
            discover=False, target_scene_numbers=bad_targets,
        )


def test_rejects_direct_match_even_if_requested(tmp_path, monkeypatch):
    _, semantic, _ = _fixtures(tmp_path)
    semantic["results"][0].update({
        "verdict": "plausible", "visual_relation": "direct",
    })
    proposals, _, workspace = _fixtures(tmp_path)
    monkeypatch.setattr(
        recovery, "load_review_workspace", lambda *a, **kw: workspace,
    )
    with pytest.raises(ValueError, match="não estão elegíveis"):
        recovery.run_semantic_remediation(
            tmp_path, "task", [],
            original_proposals=proposals,
            semantic_assessment=semantic,
            subject="Gramsci", api_key="fake-key",
            model="gemini-test", consent=True,
            discover=False, target_scene_numbers=[1],
        )


def test_rejects_human_approved_scene(tmp_path, monkeypatch):
    proposals, semantic, workspace = _fixtures(tmp_path)
    workspace["saved_review"]["scenes"][3] = {
        "editorial_review": "approved_by_human",
    }
    monkeypatch.setattr(
        recovery, "load_review_workspace", lambda *a, **kw: workspace,
    )
    with pytest.raises(ValueError, match="não estão elegíveis"):
        recovery.run_semantic_remediation(
            tmp_path, "task", [],
            original_proposals=proposals,
            semantic_assessment=semantic,
            subject="Gramsci", api_key="fake-key",
            model="gemini-test", consent=True,
            discover=False, target_scene_numbers=[4],
        )


def test_rejects_stale_media_before_discovery(tmp_path, monkeypatch):
    proposals, semantic, workspace = _fixtures(tmp_path)
    proposals["scenes"][4]["primary"] = "different-new-file.mp4"
    monkeypatch.setattr(
        recovery, "load_review_workspace", lambda *a, **kw: workspace,
    )
    with pytest.raises(ValueError, match="não estão elegíveis"):
        recovery.run_semantic_remediation(
            tmp_path, "task", [],
            original_proposals=proposals,
            semantic_assessment=semantic,
            subject="Gramsci", api_key="fake-key",
            model="gemini-test", consent=True,
            discover=False, target_scene_numbers=[5],
        )


def test_ui_tracks_group_results_and_resets_on_new_baseline():
    source = (
        Path(__file__).parents[2] / "webui" / "rick_editorial_panel.py"
    ).read_text(encoding="utf-8")
    assert "rick_ai_fix_history_" in source
    assert "Próximo grupo de cenas a recuperar" in source
    assert "pending_groups" in source
    assert "target_scene_numbers=list(selected_group)" in source
    assert "Grupos processados:" in source
    assert "Nenhuma substituição ou aprovação foi realizada." in source
    assert "st.session_state.pop(" in source
    assert "Todos os grupos sinalizados foram processados" in source
