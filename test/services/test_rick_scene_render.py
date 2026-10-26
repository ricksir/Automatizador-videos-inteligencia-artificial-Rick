"""No-API tests for opt-in source slicing on actual scene windows."""

import pytest

from app.services.rick_scene_render import plan_source_slices


def _timeline():
    return {
        "status": "ready_metadata_only",
        "duration_seconds": 9.5,
        "segments": [
            {"source_file": "a.mp4", "scene_number": 1, "start_seconds": 0, "end_seconds": 3.5},
            {"source_file": "b.mp4", "scene_number": 2, "start_seconds": 3.5, "end_seconds": 7},
            {"source_file": "a.mp4", "scene_number": 3, "start_seconds": 7, "end_seconds": 9.5},
        ],
    }


def _specs(a=20, b=20):
    return {
        "a.mp4": {"file_path": r"C:\media\a.mp4", "duration_seconds": a, "width": 1920, "height": 1080},
        "b.mp4": {"file_path": r"C:\media\b.mp4", "duration_seconds": b, "width": 1920, "height": 1080},
    }


def test_respects_scene_order_and_reuses_nonadjacent_source_from_new_offset():
    segments = plan_source_slices(_timeline(), _specs())
    assert [x["source_file"] for x in segments] == ["a.mp4", "b.mp4", "a.mp4"]
    assert [x["scene_number"] for x in segments] == [1, 2, 3]
    assert segments[0]["source_start_seconds"] == 0
    assert segments[2]["source_start_seconds"] == 3.5
    assert sum(x["duration_seconds"] for x in segments) == pytest.approx(9.6)
    assert all(x["file_path"].startswith("C:") for x in segments)


def test_short_clip_repeats_within_its_scene_without_generic_fallback():
    timeline = {
        "status": "ready_metadata_only",
        "duration_seconds": 4.0,
        "segments": [{"source_file": "a.mp4", "scene_number": 1, "start_seconds": 0, "end_seconds": 4}],
    }
    slices = plan_source_slices(timeline, _specs(a=1.5), safety_tail_seconds=0.1)
    assert len(slices) >= 3
    assert all(s["source_file"] == "a.mp4" for s in slices)
    assert sum(s["duration_seconds"] for s in slices) == pytest.approx(4.1)


@pytest.mark.parametrize("speed", [0.5, 1.0, 2.0])
def test_speed_scales_source_read_window_but_not_rendered_scene_timing(speed):
    slices = plan_source_slices(_timeline(), _specs(), clip_speed=speed)
    assert sum(s["duration_seconds"] for s in slices) == pytest.approx(9.6)
    assert sum(s["source_end_seconds"] - s["source_start_seconds"] for s in slices) == pytest.approx(9.6 * speed)


def test_end_padding_can_be_disabled_for_mock_renderers():
    slices = plan_source_slices(_timeline(), _specs(), safety_tail_seconds=0)
    assert sum(s["duration_seconds"] for s in slices) == pytest.approx(9.5)


@pytest.mark.parametrize("wrong", [
    {"status": "blocked", "segments": []},
    {"status": "preview_only_not_rendered", "segments": []},
    {"status": "ready_metadata_only", "segments": []},
])
def test_refuses_incomplete_timeline(wrong):
    with pytest.raises(ValueError):
        plan_source_slices(wrong, _specs())


def test_unavailable_source_must_fail_closed():
    with pytest.raises(ValueError, match="not among downloaded"):
        plan_source_slices(_timeline(), {"a.mp4": _specs()["a.mp4"]})


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf"), 0.0001])
def test_invalid_actual_source_duration_rejected(duration):
    with pytest.raises(ValueError):
        plan_source_slices(_timeline(), _specs(a=duration))


def test_cross_scene_gaps_rejected():
    t = _timeline()
    t["segments"][1]["start_seconds"] = 3.7
    with pytest.raises(ValueError):
        plan_source_slices(t, _specs())


def test_rejects_speed_zero_and_bad_tail():
    with pytest.raises(ValueError):
        plan_source_slices(_timeline(), _specs(), clip_speed=0)
    with pytest.raises(ValueError):
        plan_source_slices(_timeline(), _specs(), safety_tail_seconds=1)


def test_no_network_needed_or_unverified_content_guaranteed():
    slices = plan_source_slices(_timeline(), _specs())
    assert slices
    assert not any("verified" in key or "api" in key for item in slices for key in item)


def test_bound_large_timeline():
    timeline = {
        "status": "ready_metadata_only",
        "duration_seconds": 1300,
        "segments": [{"source_file": "a.mp4", "start_seconds": 0, "end_seconds": 1300}],
    }
    with pytest.raises(ValueError, match="maximum source slices"):
        plan_source_slices(timeline, _specs(a=0.1), safety_tail_seconds=0)
