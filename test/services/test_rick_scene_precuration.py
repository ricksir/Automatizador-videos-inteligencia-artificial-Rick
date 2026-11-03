"""Rick scene pre-curation regression tests: no provider calls, paid APIs or uploads."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import rick_scene_discovery as discovery
from app.services.rick_scene_precuration import build_precuration, scene_intent
from app.services.rick_precuration_workspace import (
    _inventory_signature, load_precuration, run_scene_precuration,
)


def test_intent_depends_on_spoken_excerpt_not_previous_gramsci_query():
    person = scene_intent(
        {"text": "Gramsci estudou como ideias dominam",
         "search_term": "Gramsci theory"},
        "O filósofo Gramsci e a luta de posições",
    )
    election = scene_intent(
        {"text": "Nas eleições brasileiras vemos exatamente isso:",
         "search_term": "Gramsci Brazil"},
        "O filósofo Gramsci e a luta de posições",
    )
    assert person["kind"] == "historical_person"
    assert "Gramsci" in person["query"]
    assert election["kind"] == "elections"
    assert "elections voting" in election["query"]
    assert election["person"] is None
    assert election["alignment"] == "estimated"


def test_waterfall_never_overrides_actual_gramsci_portrait():
    scenes = [{
        "number": 1,
        "text": "Gramsci estudou como ideias dominam",
        "search_term": "Gramsci theory",
        "start_seconds": 0,
        "end_seconds": 2,
    }]
    metadata = {
        "waterfall.mp4": {
            "search_term": "Gramsci Brazil", "title": "Waterfall landscape",
            "source_page": "https://pixabay.com/videos/waterfall/",
            "provider": "pixabay",
        },
        "portrait.mp4": {
            "search_term": "Gramsci portrait photograph",
            "title": "File:Gramsci.png",
            "source_page": "https://commons.wikimedia.org/wiki/File:Gramsci.png",
            "provider": "Wikimedia Commons", "scene_number": 1,
        },
    }
    report = build_precuration(
        "O filósofo Gramsci", scenes, metadata, list(metadata),
    )
    assert report["proposed_count"] == 1
    assert report["scenes"][0]["primary"] == "portrait.mp4"
    assert all(item["file"] != "waterfall.mp4"
               for item in report["scenes"][0]["alternatives"])
    assert report["scenes"][0]["human_approved"] is False
    assert report["scenes"][0]["visual_content_verified"] is False


def test_elections_prioritizes_election_video_not_person_photo():
    scenes = [
        {"text": "Gramsci estudou como ideias dominam", "search_term": "Gramsci theory"},
        {"text": "Nas eleições brasileiras a participação ocorre nas urnas",
         "search_term": "Gramsci Brazil"},
    ]
    meta = {
        "portrait.mp4": {
            "title": "Gramsci historical portrait",
            "search_term": "Gramsci historical portrait photograph",
            "source_page": "https://commons.wikimedia.org/wiki/File:Gramsci.png",
        },
        "election.mp4": {
            "search_term": "elections voting ballot people",
            "title": "Brazil elections voting ballot",
            "source_page": "https://videos.pexels.com/path.mp4",
        },
    }
    report = build_precuration("O filósofo Gramsci", scenes, meta, list(meta))
    assert report["scenes"][0]["primary"] == "portrait.mp4"
    assert report["scenes"][1]["primary"] == "election.mp4"


def test_anti_repetition_is_bounded_and_unresolved_is_not_randomly_filled():
    scenes = [{"text": "Gramsci estudou", "search_term": "Gramsci portrait"}
              for _ in range(5)]
    metadata = {
        "portrait.mp4": {"title": "Gramsci portrait", "search_term": "Gramsci portrait"}
    }
    report = build_precuration(
        "O filósofo Gramsci", scenes, metadata, list(metadata), max_uses=2,
    )
    assert [s["primary"] for s in report["scenes"]] == [
        "portrait.mp4", "portrait.mp4", None, None, None,
    ]
    assert report["unresolved_count"] == 3
    assert "NÃO probabilidades" in report["warning"]
    assert not any(s["rights_verified"] for s in report["scenes"])


def test_best_available_is_deterministic_and_uses_alternatives():
    scene = {"text": "Gramsci estudou", "search_term": "Gramsci portrait"}
    candidates = {
        "a.mp4": {"search_term": "Gramsci portrait", "title": "Gramsci portrait"},
        "b.mp4": {"search_term": "Gramsci portrait", "title": "Gramsci portrait"},
        "c.mp4": {"search_term": "Gramsci portrait", "title": "Gramsci portrait"},
    }
    report = build_precuration(
        "O filósofo Gramsci", [scene] * 3, candidates, list(candidates),
    )
    assigned = [s["primary"] for s in report["scenes"]]
    assert assigned == ["a.mp4", "b.mp4", "a.mp4"]
    assert report["scenes"][0]["alternatives"]


def test_external_video_links_cannot_be_downloaded():
    assert discovery._trusted_video_url(
        "https://videos.pexels.com/video-files/123/c.mp4"
    )
    for url in (
        "http://videos.pexels.com/a.mp4",
        "https://videos.pexels.com.evil.example/a.mp4",
        "https://user:pw@videos.pexels.com/a.mp4",
        "https://videos.pexels.com:443/a.mp4",
        "https://example.com/a.mp4",
        "https://cdn.pixabay.com/a.jpg",
    ):
        assert not discovery._trusted_video_url(url)
        with pytest.raises(ValueError):
            discovery._download_stock_clip(url)


def test_discovery_will_not_use_unrelated_stock_for_generic_scene(monkeypatch):
    calls = []
    monkeypatch.setattr(
        discovery, "_stock_provider",
        lambda: ("pexels", lambda *args: (calls.append(args) or [])),
    )
    report = discovery.discover_scene_media(
        "/not-used", "unused", subject="Como surgiram as ideias",
        scenes=[{"text": "isso mudou o mundo", "search_term": "Gramsci Brazil"}],
        source_metadata={},
    )
    assert report["imported_count"] == 0
    assert calls == []


def test_discovery_imports_video_once_with_scene_query_and_source(monkeypatch):
    searches, imports = [], []
    monkeypatch.setattr(
        discovery, "_stock_provider",
        lambda: ("pexels", lambda query, duration, aspect: (
            searches.append(query) or [
                SimpleNamespace(url="https://videos.pexels.com/video-files/7/clip.mp4",
                                source_info={
                                    "asset_id": "7",
                                    "source_page": "https://www.pexels.com/video/7/"
                                }),
            ]
        )),
    )
    monkeypatch.setattr(discovery, "_download_stock_clip", lambda url: b"FAKE")
    monkeypatch.setattr(
        discovery, "import_editorial_material",
        lambda *a, **k: (imports.append(k) or "imported.mp4"),
    )
    report = discovery.discover_scene_media(
        "/unused", "unused", subject="Política e sociedade",
        scenes=[
            {"text": "Nas eleições as urnas recebem os votos"},
            {"text": "Votar é importante para as eleições"},
        ],
        source_metadata={},
    )
    assert report["imported_count"] == 1
    assert len(imports) == 1
    assert imports[0]["scene_number"] == 1
    assert imports[0]["search_term"] == "elections voting ballot people"
    assert "pexels.com/video/7" in imports[0]["source_note"]
    assert report["rights_verified"] is False


def _workspace(tmp_path, *, source_term="Gramsci portrait"):
    root = tmp_path / "tasks"
    folder = root / "task-123"
    folder.mkdir(parents=True, exist_ok=True)
    video = folder / "portrait.mp4"
    video.write_bytes(b"owned-MP4")
    return root, folder, {
        "preview_sha256": "a" * 64,
        "preview": {"scenes": [{"text": "Gramsci estudou",
                                "search_term": "Gramsci portrait",
                                "start_seconds": 0, "end_seconds": 2}]},
        "paths": {"portrait.mp4": str(video)},
        "source_metadata": {
            "portrait.mp4": {
                "search_term": source_term, "title": "Gramsci portrait",
                "provider": "local", "source_page": "Commons"
            }
        },
    }


def test_saved_precuration_is_not_an_approval_and_invalidates_on_media_change(
    tmp_path, monkeypatch,
):
    root, folder, workspace = _workspace(tmp_path)
    monkeypatch.setattr(
        "app.services.rick_precuration_workspace.load_review_workspace",
        lambda *args, **kwargs: workspace,
    )
    report = run_scene_precuration(
        root, "task-123", [], subject="O filósofo Gramsci",
    )
    assert report["proposed_count"] == 1
    assert load_precuration(root, "task-123", workspace) == report
    assert not (folder / "rick_editorial_review.json").exists()
    assert not (folder / "rick_auto_exports").exists()
    saved = json.loads((folder / "rick_scene_precuration.json").read_text(encoding="utf-8"))
    assert saved["preview_sha256"] == workspace["preview_sha256"]
    assert saved["inventory_sha256"] == _inventory_signature(workspace)
    (folder / "portrait.mp4").write_bytes(b"changed contents")
    assert load_precuration(root, "task-123", workspace) is None


def test_old_precuration_does_not_survive_preview_change(tmp_path, monkeypatch):
    root, _folder, workspace = _workspace(tmp_path)
    monkeypatch.setattr(
        "app.services.rick_precuration_workspace.load_review_workspace",
        lambda *args, **kwargs: workspace,
    )
    run_scene_precuration(root, "task-123", [], subject="O filósofo Gramsci")
    changed = {**workspace, "preview_sha256": "b" * 64}
    assert load_precuration(root, "task-123", changed) is None
