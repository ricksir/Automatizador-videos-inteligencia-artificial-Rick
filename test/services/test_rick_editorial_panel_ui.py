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
    assert code.index('chosen = st.selectbox(') < code.index('with st.form(')
    assert code.index('st.video(source_path)') < code.index('with st.form(')
    assert 'on_change=_clear_scene_evidence' in code
    assert 'st.form_submit_button("Salvar esta cena"' in code
    assert 'retained_human_decisions(old_scenes, exclude_scene=idx)' in code
    assert 'st.rerun()' in code
    assert 'save_editorial_workspace_review(' in code
    assert 'generate_final_videos(' not in code
    assert 'material.download_videos(' not in code
