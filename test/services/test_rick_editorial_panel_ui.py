"""Offline regression checks for Rick's human scene-review interface."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from webui import rick_editorial_panel as panel


def test_changing_video_requires_new_human_verification(monkeypatch):
    session_state = {
        "rick_editorial_decision_task-1_3": "Aprovar",
        "rick_editorial_source_task-1_3": "old source",
        "rick_editorial_content_task-1_3": True,
        "rick_editorial_rights_task-1_3": True,
    }
    monkeypatch.setattr(panel, "st", SimpleNamespace(session_state=session_state))
    panel._clear_scene_evidence("task-1", 3)
    assert session_state == {
        "rick_editorial_decision_task-1_3": "Pendente",
        "rick_editorial_source_task-1_3": "",
        "rick_editorial_content_task-1_3": False,
        "rick_editorial_rights_task-1_3": False,
    }


def test_progress_uses_only_saved_complete_human_approvals():
    approved = {
        "editorial_review": "approved_by_human",
        "editorial_source_note": "Verified rights/source",
        "editorial_content_checked": True,
        "editorial_rights_checked": True,
    }
    incomplete = {
        **approved, "editorial_rights_checked": False,
    }
    scenes = [approved, incomplete, {"editorial_review": "rejected"}, {}]
    assert panel._review_progress(scenes, 4) == (1, 1)
    assert panel._review_progress([], 24) == (0, 0)


def test_video_preview_updates_before_any_save_and_per_scene_submission():
    code = (Path(__file__).parents[2] / "webui" / "rick_editorial_panel.py").read_text(
        encoding="utf-8"
    )
    assert code.index('suggested_choice = st.selectbox(') < code.index('with st.form(')
    assert code.index('st.video(source_path)') < code.index('with st.form(')
    assert 'on_change=_select_scene_material' in code
    assert 'st.form_submit_button("Salvar esta cena"' in code
    assert 'retained_human_decisions(old_scenes, exclude_scene=idx)' in code
    assert 'st.rerun()' in code
    assert 'save_editorial_workspace_review(' in code
    assert 'generate_final_videos(' not in code
    assert 'material.download_videos(' not in code


def test_switching_between_metadata_and_other_media_clears_old_evidence(monkeypatch):
    suffix = "task-a_2"
    state = {
        f"rick_editorial_decision_{suffix}": "Aprovar",
        f"rick_editorial_source_{suffix}": "Checked source",
        f"rick_editorial_content_{suffix}": True,
        f"rick_editorial_rights_{suffix}": True,
        f"rick_editorial_material_v4_{suffix}": "portrait.mp4",
        f"rick_editorial_other_v1_{suffix}": "waterfall.mp4",
        "rick_editorial_material_v4_task-b_2": "unrelated.mp4",
    }
    monkeypatch.setattr(panel, "st", SimpleNamespace(session_state=state))
    panel._select_scene_material("task-a", 2, "suggested")
    assert state[f"rick_editorial_other_v1_{suffix}"] is None
    assert state[f"rick_editorial_material_v4_{suffix}"] == "portrait.mp4"
    assert state[f"rick_editorial_content_{suffix}"] is False
    assert state[f"rick_editorial_rights_{suffix}"] is False
    assert state[f"rick_editorial_source_{suffix}"] == ""
    assert state[f"rick_editorial_decision_{suffix}"] == "Pendente"
    state[f"rick_editorial_material_v4_{suffix}"] = "portrait.mp4"
    panel._select_scene_material("task-a", 2, "other")
    assert state[f"rick_editorial_material_v4_{suffix}"] is None
    assert state["rick_editorial_material_v4_task-b_2"] == "unrelated.mp4"


def test_unmatched_clips_are_only_shown_in_manual_expandable_library():
    code = (Path(__file__).parents[2] / "webui" / "rick_editorial_panel.py").read_text(
        encoding="utf-8"
    )
    assert "groups = classify_review_materials(" in code
    assert 'groups["suggested"]' in code
    assert 'groups["other"]' in code
    assert "Nenhum material correspondente foi identificado para esta cena." in code
    assert "Outros materiais disponíveis na tarefa" in code
    assert 'chosen = other_choice if other_choice is not None else suggested_choice' in code
    assert code.index("chosen = other_choice") < code.index("with st.form(")
    assert "O nome histórico aparece somente nos metadados" in code


def test_precuration_review_mode_prioritizes_unmatched_and_low_score():
    proposals = {
        1: {"primary": "portrait.mp4", "metadata_score": 90},
        2: {"primary": None, "metadata_score": 0},
        3: {"primary": "election.mp4", "metadata_score": 45},
        4: {"primary": "book.mp4", "metadata_score": 75},
    }
    assert panel._priority_scene_numbers(proposals, 5) == [2, 3, 5]


def test_precuration_is_displayed_without_marking_human_approval():
    source = (Path(__file__).parents[2] / "webui" / "rick_editorial_panel.py").read_text(
        encoding="utf-8"
    )
    assert "Rick — Pré-curadoria automática por cena" in source
    assert "load_precuration(tasks_root, selected_id, workspace)" in source
    assert "build_precuration(" in source
    assert "run_scene_precuration(" in source
    assert 'discover=True' in source
    assert "proposed_primary = proposed.get(\"primary\")" in source
    assert source.index("proposed_primary = proposed.get") < source.index("with st.form(")
    assert "Só cenas sem sugestão ou com score baixo" in source
