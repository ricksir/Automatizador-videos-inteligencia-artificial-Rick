"""No-network tests of Rick 02B2A scene-to-stock-candidate mapping."""

import json

import pytest

from app.services.rick_scene_assignment import assign_scene_candidates
from app.services.rick_scene_plan import build_scene_plan


def _plan(n: int = 4):
    # Four scenes with two repeating consultation groups (and estimated time).
    return {
        "alignment": "estimated",
        "scenes": [
            {
                "number": i + 1,
                "start_seconds": 4.0 * i,
                "end_seconds": 4.0 * (i + 1),
                "text": f"Cena {i + 1}",
                "search_term": ["old books", "election rally", "old books", "election rally"][i],
                "media_verified": False,
            }
            for i in range(n)
        ],
    }


def test_assigns_by_exact_query_not_global_random_stock():
    records = [
        {"local_file": "books.mp4", "search_term": "old books", "provider": "pixabay", "asset_id": "10"},
        {"local_file": "votes.mp4", "search_term": "election rally", "provider": "pixabay", "asset_id": "11"},
        {"local_file": "space.mp4", "search_term": "outer space", "provider": "pixabay", "asset_id": "12"},
    ]
    output = assign_scene_candidates(_plan(), records)
    assert [s["assigned_material_file"] for s in output["scenes"]] == [
        "books.mp4", "votes.mp4", "books.mp4", "votes.mp4"
    ]
    assert output["scenes_reusing_source"] == 2
    assert output["distinct_sources_used"] == 2
    assert output["status"] == "preview_only_not_rendered"
    assert all(s["media_verified"] is False for s in output["scenes"])
    json.dumps(output)


def test_chooses_distinct_files_before_reuse_and_deterministically():
    sources = [
        {"local_file": "a.mp4", "search_term": "old books", "provider": "pixabay", "asset_id": "1"},
        {"local_file": "b.mp4", "search_term": "old books", "provider": "pixabay", "asset_id": "2"},
        {"local_file": "c.mp4", "search_term": "election rally", "provider": "pixabay", "asset_id": "3"},
    ]
    first = assign_scene_candidates(_plan(), sources)
    second = assign_scene_candidates(_plan(), sources)
    assert first == second
    assert [s["assigned_material_file"] for s in first["scenes"]] == [
        "a.mp4", "c.mp4", "b.mp4", "c.mp4"
    ]


def test_different_renditions_same_origin_are_not_assumed_distinct():
    sources = [
        {"local_file": "a720.mp4", "search_term": "old books", "provider": "pixabay", "asset_id": "1"},
        {"local_file": "a1080.mp4", "search_term": "old books", "provider": "pixabay", "asset_id": "1"},
        {"local_file": "b.mp4", "search_term": "old books", "provider": "pixabay", "asset_id": "2"},
    ]
    plan = {"scenes": [_plan()["scenes"][0], _plan()["scenes"][2]]}
    out = assign_scene_candidates(plan, sources)
    assert [s["assigned_material_file"] for s in out["scenes"]] == ["a720.mp4", "b.mp4"]
    assert out["scenes_reusing_source"] == 0


def test_missing_matching_query_is_not_silently_replaced_with_unrelated_footage():
    source = [{"local_file": "beach.mp4", "search_term": "ocean holiday"}]
    out = assign_scene_candidates(_plan(), source)
    assert out["scenes_with_term_candidate"] == 0
    assert out["scenes_without_term_candidate"] == 4
    assert all(scene["assigned_material_file"] is None for scene in out["scenes"])
    assert "scene_media_missing" in {item["code"] for item in out["warnings"]}


def test_filters_to_downloaded_files_and_never_exposes_source_url_or_keys():
    records = [
        {"local_file": "actual.mp4", "search_term": "old books", "source_page": "https://example.com/?key=SECRET"},
        {"local_file": "not-downloaded.mp4", "search_term": "old books"},
        {"local_file": "../traversal.mp4", "search_term": "old books"},
        {"local_file": r"folder\escape.mp4", "search_term": "old books"},
    ]
    plan = {"scenes": [_plan()["scenes"][0]]}
    out = assign_scene_candidates(plan, records, available_files=["C:/temporary/actual.mp4"])
    assert out["scenes"][0]["assigned_material_file"] == "actual.mp4"
    assert out["scenes"][0]["candidate_count"] == 1
    assert "SECRET" not in json.dumps(out)
    assert "source_page" not in json.dumps(out)


def test_normalizes_whitespace_and_case_in_terms_but_does_not_invent_synonyms():
    plan = {"scenes": [{
        "number": 1, "start_seconds": 0, "end_seconds": 4,
        "text": "Um livro.", "search_term": " OLD   Books ", "media_verified": False
    }]}
    rec = [{"local_file": "book.mp4", "search_term": "old books"}]
    assert assign_scene_candidates(plan, rec)["scenes_with_term_candidate"] == 1


def test_empty_sources_returns_safe_reviewable_preview():
    plan = build_scene_plan("Gramsci escreveu sobre ideias e política.", ["Gramsci portrait"], 4.0)
    out = assign_scene_candidates(plan, [], available_files=[])
    assert out["scenes_without_term_candidate"] == plan["scene_count"]
    assert out["scenes"][0]["media_verified"] is False


@pytest.mark.parametrize(
    "plan,sources,files",
    [
        ({}, [], []),
        ({"scenes": None}, [], []),
        ({"scenes": ["malformed"]}, [], []),
        (_plan(), "malformed", []),
        (_plan(), [], "malformed"),
    ],
)
def test_malformed_metadata_rejected(plan, sources, files):
    with pytest.raises(ValueError):
        assign_scene_candidates(plan, sources, available_files=files)
