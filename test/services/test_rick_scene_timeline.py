"""Offline tests for strict render preflight of Rick scene candidates."""

import copy
import json
import math

import pytest

from app.services.rick_scene_timeline import build_scene_render_preflight


def sample():
    return {
        "alignment": "estimated",
        "scene_count": 3,
        "scenes": [
            {
                "number": 1, "start_seconds": 0, "end_seconds": 3.5,
                "assigned_material_file": "books.mp4",
                "match_status": "term_match_unverified",
            },
            {
                "number": 2, "start_seconds": 3.5, "end_seconds": 8,
                "assigned_material_file": "election.mp4",
                "match_status": "term_match_unverified",
            },
            {
                "number": 3, "start_seconds": 8, "end_seconds": 12,
                "assigned_material_file": "parliament.mp4",
                "match_status": "term_match_unverified",
            },
        ],
    }


FILES = [
    r"C:\\temp\\books.mp4",
    r"C:\\temp\\election.mp4",
    r"C:\\temp\\parliament.mp4",
]


def test_complete_scene_timeline_has_exact_durations_without_filler():
    result = build_scene_render_preflight(sample(), FILES, 12.0, max_clip_seconds=4)
    assert result["status"] == "ready_metadata_only"
    assert result["media_verified"] is False
    assert result["scene_count"] == 3
    assert [s["source_file"] for s in result["segments"]] == [
        "books.mp4", "election.mp4", "election.mp4", "parliament.mp4"
    ]
    assert all(s["duration_seconds"] <= 4 for s in result["segments"])
    assert result["segments"][0]["start_seconds"] == 0
    assert result["segments"][-1]["end_seconds"] == 12
    assert sum(s["duration_seconds"] for s in result["segments"]) == pytest.approx(12)
    assert json.loads(json.dumps(result)) == result


def test_missing_scene_blocks_entire_render_without_generic_stock_fallback():
    plan = sample()
    plan["scenes"][1]["assigned_material_file"] = None
    plan["scenes"][1]["match_status"] = "missing_term_match"
    result = build_scene_render_preflight(plan, FILES, 12)
    assert result["status"] == "blocked"
    assert result["segments"] == []
    assert result["blockers"] == [{"code": "scene_missing_candidate", "scene_number": 2}]


def test_unavailable_file_blocks():
    result = build_scene_render_preflight(sample(), FILES[:-1], 12)
    assert result["status"] == "blocked"
    assert result["blockers"][0]["scene_number"] == 3


def test_duplicate_filename_paths_cannot_resolve_ambiguously():
    result = build_scene_render_preflight(sample(), FILES + ["/home/user/books.mp4"], 12)
    assert result["status"] == "blocked"
    assert result["blockers"][0]["scene_number"] == 1


def test_slash_backslash_and_nonvideo_manifest_filename_cannot_pass():
    for bad in ("../books.mp4", r"folder\books.mp4", "books.txt", "", ".", None):
        plan = sample()
        plan["scenes"][0]["assigned_material_file"] = bad
        assert build_scene_render_preflight(plan, FILES, 12)["status"] == "blocked"


@pytest.mark.parametrize("duration", [35.0, 42.789, 49.9999, 50])
def test_fractional_and_boundary_durations(duration):
    plan = {
        "scene_count": 1,
        "scenes": [{
            "start_seconds": 0,
            "end_seconds": duration,
            "assigned_material_file": "books.mp4",
            "match_status": "term_match_unverified",
        }],
    }
    result = build_scene_render_preflight(plan, FILES, duration, max_clip_seconds=4)
    assert result["status"] == "ready_metadata_only"
    assert result["segments"][-1]["end_seconds"] == duration
    assert sum(s["duration_seconds"] for s in result["segments"]) == pytest.approx(duration)
    assert all(0 < s["duration_seconds"] <= 4 for s in result["segments"])


def test_adjacent_reused_source_warns():
    plan = sample()
    plan["scenes"][1]["assigned_material_file"] = "books.mp4"
    result = build_scene_render_preflight(plan, FILES, 12)
    assert result["status"] == "ready_metadata_only"
    assert any(w["code"] == "scene_adjacent_source_reused" for w in result["warnings"])


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x["scenes"][1].update(start_seconds=3.7),
        lambda x: x["scenes"][1].update(start_seconds=3.0),
        lambda x: x["scenes"][0].update(end_seconds=0),
        lambda x: x["scenes"][2].update(end_seconds=14),
        lambda x: x.update(scene_count=5),
    ],
)
def test_bad_timing_and_metadata_raises(change):
    plan = sample()
    change(plan)
    with pytest.raises(ValueError):
        build_scene_render_preflight(plan, FILES, 12)


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True, None])
def test_invalid_audio_duration_rejected(value):
    with pytest.raises(ValueError):
        build_scene_render_preflight(sample(), FILES, value)


@pytest.mark.parametrize("value", [0, -2, float("inf"), True, None])
def test_invalid_clip_duration_rejected(value):
    with pytest.raises(ValueError):
        build_scene_render_preflight(sample(), FILES, 12, max_clip_seconds=value)


def test_empty_and_incompatible_input_rejected():
    with pytest.raises(ValueError):
        build_scene_render_preflight({"scenes": []}, FILES, 12)
    with pytest.raises(ValueError):
        build_scene_render_preflight(sample(), "books.mp4", 12)


def test_user_manifest_not_mutated():
    original = sample()
    initial = copy.deepcopy(original)
    build_scene_render_preflight(original, FILES, 12)
    assert original == initial


def test_one_scene_with_no_candidate_is_blocked():
    plan = {"scenes": [{
        "start_seconds": 0, "end_seconds": 4,
        "assigned_material_file": None,
        "match_status": "missing_term_match",
    }]}
    assert build_scene_render_preflight(plan, FILES, 4)["status"] == "blocked"
