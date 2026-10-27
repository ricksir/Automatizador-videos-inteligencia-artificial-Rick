"""Offline tests: explicit human review must be complete, never inferred."""
import pytest

from app.services.rick_editorial_review import build_editorial_review
from app.services.rick_scene_timeline import build_scene_render_preflight


def preview():
    return {
        "scene_count": 2,
        "alignment": "estimated",
        "scenes": [
            {"number": 1, "start_seconds": 0, "end_seconds": 2,
             "text": "Fotografia do pensador", "search_term": "historian",
             "assigned_material_file": "generic.mp4",
             "match_status": "term_match_unverified"},
            {"number": 2, "start_seconds": 2, "end_seconds": 4,
             "text": "Contexto eleitoral", "search_term": "voting",
             "assigned_material_file": "vote.mp4",
             "match_status": "term_match_unverified"},
        ],
    }


FILES = ["C:/media/portrait.mp4", "C:/media/vote.mp4", "C:/media/generic.mp4"]


def accept(scene_number, filename):
    return {
        "scene_number": scene_number, "decision": "approve",
        "selected_file": filename, "source_note": "Conferido manualmente no acervo",
        "rights_checked": True, "content_checked": True,
    }


def test_manual_override_and_preflight_compatibility():
    result = build_editorial_review(
        preview(), FILES, [accept(1, "portrait.mp4"), accept(2, "vote.mp4")]
    )
    assert result["status"] == "ready_human_reviewed"
    assert result["human_approved_count"] == 2
    assert result["scenes"][0]["assigned_material_file"] == "portrait.mp4"
    assert result["visual_identity_verified_automatically"] is False
    assert result["scenes"][0]["automated_identity_verified"] is False
    plan = build_scene_render_preflight(result, FILES, 4, max_clip_seconds=2)
    assert plan["status"] == "ready_metadata_only"
    assert [s["source_file"] for s in plan["segments"]] == ["portrait.mp4", "vote.mp4"]


def test_unreviewed_scene_blocks_even_if_search_term_matched():
    result = build_editorial_review(preview(), FILES, [accept(1, "portrait.mp4")])
    assert result["status"] == "blocked"
    assert result["human_approved_count"] == 1
    assert result["blockers"] == [{"scene_number": 2, "code": "review_missing"}]


def test_rejection_blocks_without_silent_generic_fallback():
    result = build_editorial_review(
        preview(), FILES,
        [{"scene_number": 1, "decision": "reject"}, accept(2, "vote.mp4")]
    )
    assert result["status"] == "blocked"
    assert result["scenes"][0]["assigned_material_file"] is None
    assert result["scenes"][0]["match_status"] == "editorial_rejected"


@pytest.mark.parametrize("field, value, blocker", [
    ("selected_file", "../portrait.mp4", "file_missing_or_ambiguous"),
    ("selected_file", "absent.mp4", "file_missing_or_ambiguous"),
    ("selected_file", "C:\\tmp\\portrait.mp4", "file_missing_or_ambiguous"),
    ("selected_file", "portrait.jpg", "file_missing_or_ambiguous"),
    ("source_note", "", "provenance_note_missing"),
    ("rights_checked", False, "rights_review_missing"),
    ("content_checked", False, "content_review_missing"),
])
def test_incomplete_approval_fails_closed(field, value, blocker):
    choice = accept(1, "portrait.mp4")
    choice[field] = value
    result = build_editorial_review(preview(), FILES, [choice, accept(2, "vote.mp4")])
    assert result["status"] == "blocked"
    assert result["blockers"][0]["code"] == blocker


def test_ambiguous_downloaded_basename_rejected():
    files = FILES + ["/another/portrait.mp4"]
    result = build_editorial_review(preview(), files, [accept(1, "portrait.mp4"), accept(2, "vote.mp4")])
    assert result["status"] == "blocked"
    assert result["blockers"][0]["code"] == "file_missing_or_ambiguous"


def test_duplicate_decisions_not_permitted():
    with pytest.raises(ValueError, match="duplicate"):
        build_editorial_review(preview(), FILES, [accept(1, "portrait.mp4"), accept(1, "portrait.mp4")])


def test_wrong_decision_type_not_permitted():
    with pytest.raises(ValueError):
        build_editorial_review(preview(), FILES, [{"scene_number": True, "decision": "reject"}])


def test_no_automatic_approval_when_no_decisions():
    result = build_editorial_review(preview(), FILES, [])
    assert result["status"] == "blocked"
    assert result["human_approved_count"] == 0
