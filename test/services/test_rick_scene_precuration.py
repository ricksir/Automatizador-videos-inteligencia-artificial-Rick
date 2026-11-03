"""Rick scene pre-curation regression tests: no provider calls, paid APIs or uploads."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services import rick_scene_discovery as discovery
from app.services.rick_scene_precuration import (
    build_precuration, scene_intent, scene_search_context,
)
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
    assert assigned == ["a.mp4", "b.mp4", "c.mp4"]
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


def test_context_search_reconstructs_fragment_without_changing_scene_times():
    fragments = [
        {"text": "a sociedade e como", "start_seconds": 2, "end_seconds": 4},
        {"text": "grupos podem mudar isso sem", "start_seconds": 4, "end_seconds": 6},
        {"text": "precisar de revoluções violentas.", "start_seconds": 6, "end_seconds": 8},
    ]
    intent = scene_search_context(
        fragments, 0, "O filósofo Gramsci e suas ideias",
    )
    assert intent["kind"] == "demonstrations"
    assert intent["context_derived"] is True
    assert intent["text"] == "a sociedade e como"
    assert intent["alignment"] == "estimated"
    assert fragments[0]["start_seconds"] == 2


def test_discovery_searches_unresolved_scenes_before_old_candidates(monkeypatch):
    queries = []

    def fake_search(query, *_args):
        queries.append(query)
        return []

    monkeypatch.setattr(
        discovery, "_stock_provider", lambda: ("pexels", fake_search),
    )
    result = discovery.discover_scene_media(
        "/unused", "task-1", subject="História geral",
        scenes=[
            {"text": "Nas eleições as pessoas participam da votação"},
            {"text": "Livros e manuscritos mostram documentos antigos"},
        ],
        source_metadata={},
        priority_scene_numbers=[2, 1],
        max_stills=0,
    )
    assert queries == [
        "historical books documents manuscript",
        "elections voting ballot people",
    ]
    assert result["priority_scene_numbers"] == [2, 1]


def test_discovery_collects_two_distinct_contextual_videos(monkeypatch):
    imported = []
    clips = [
        SimpleNamespace(
            url=f"https://videos.pexels.com/video-files/{n}/clip.mp4",
            source_info={
                "asset_id": str(n),
                "source_page": f"https://www.pexels.com/video/{n}/",
            },
        )
        for n in (11, 12, 13)
    ]
    monkeypatch.setattr(
        discovery, "_stock_provider", lambda: ("pexels", lambda *a: clips),
    )
    monkeypatch.setattr(discovery, "_download_stock_clip", lambda url: b"MP4")
    monkeypatch.setattr(
        discovery, "import_editorial_material",
        lambda *a, **kw: (imported.append(kw) or f"saved-{len(imported)}.mp4"),
    )
    report = discovery.discover_scene_media(
        "/unused", "task-1", subject="Mundo político",
        scenes=[{"text": "Nas eleições brasileiras as pessoas votam"}],
        source_metadata={}, max_stills=0, max_clips=2,
    )
    assert report["imported_count"] == 2
    assert [r["asset_id"] for r in imported] == ["pexels:11", "pexels:12"]
    assert report["rights_verified"] is False


def test_discovery_priority_rejects_invalid_indices():
    with pytest.raises(ValueError, match="prioritárias"):
        discovery.discover_scene_media(
            "/unused", "task-1", subject="História geral",
            scenes=[{"text": "Nas eleições"}], source_metadata={},
            priority_scene_numbers=[0],
            max_stills=0, max_clips=0,
        )


def test_contextual_search_candidate_is_ranked_for_short_speech_fragment():
    """Searching the full sentence is useful only if ranking uses that context."""
    scenes = [
        {"text": "a sociedade e como", "search_term": "Gramsci theory"},
        {"text": "grupos podem mudar isso sem", "search_term": "Gramsci theory"},
        {"text": "precisar de revoluções violentas.", "search_term": "Gramsci theory"},
    ]
    materials = {
        "peaceful-change.mp4": {
            "search_term": "civil demonstration public gathering",
            "title": "civil demonstration public gathering",
            "scene_number": 1, "provider": "pexels",
            "source_page": "https://www.pexels.com/video/11/",
            "media_kind": "video",
        }
    }
    report = build_precuration(
        "O filósofo Gramsci", scenes, materials, list(materials)
    )
    assert report["scenes"][0]["intent"]["context_derived"] is True
    assert report["scenes"][0]["primary"] == "peaceful-change.mp4"
    assert report["scenes"][0]["status"] == "proposal_for_human_review"
    assert report["scenes"][0]["visual_content_verified"] is False


def test_scarcity_first_does_not_spend_only_portrait_on_generic_book_scene():
    scenes = [
        {"text": "Livros e manuscritos antigos contam a história",
         "search_term": "historical books documents manuscript"},
        {"text": "Gramsci estudou e escreveu",
         "search_term": "Gramsci theory"},
    ]
    metadata = {
        "portrait.mp4": {
            "title": "Gramsci historical portrait",
            "search_term": "historical books documents manuscript",
            "source_page": "https://commons.wikimedia.org/wiki/File:Gramsci.png",
            "provider": "Commons", "scene_number": 1,
        },
        "books.mp4": {
            "title": "historical books manuscripts",
            "search_term": "historical books documents manuscript",
            "source_page": "https://www.pexels.com/video/222/",
            "provider": "pexels",
        },
    }
    report = build_precuration(
        "O filósofo Gramsci", scenes, metadata, list(metadata), max_uses=1,
    )
    assert report["proposed_count"] == 2
    assert report["scenes"][0]["primary"] == "books.mp4"
    assert report["scenes"][1]["primary"] == "portrait.mp4"
    assert report["scenes"][0]["blocker"] == "proposta_por_metadados"


def test_unresolved_scene_distinguishes_missing_metadata_from_reuse_limit():
    unknown = build_precuration(
        "Tema geral",
        [{"text": "Nas eleições as pessoas votam"}],
        {"random.mp4": {"title": "Waterfall nature landscape"}},
        ["random.mp4"],
    )
    assert unknown["scenes"][0]["primary"] is None
    assert unknown["scenes"][0]["blocker"] == (
        "sem_correspondencia_suficiente_nos_metadados"
    )
    assert unknown["scenes"][0]["eligible_candidates"] == 0

    same = [{"text": "Nas eleições as pessoas votam"}] * 2
    meta = {
        "voting.mp4": {
            "title": "elections voting ballot people",
            "search_term": "elections voting ballot people",
        }
    }
    limited = build_precuration("Eleições", same, meta, list(meta), max_uses=1)
    assert limited["proposed_count"] == 1
    assert limited["scenes"][1]["blocker"] == "limite_de_repeticao_atingido"
    assert limited["scenes"][1]["eligible_candidates"] == 1


def test_alternate_stock_provider_finds_media_when_first_is_empty(monkeypatch):
    calls = []
    imported = []

    def pexels(query, *_args):
        calls.append(("pexels", query))
        return []

    def pixabay(query, *_args):
        calls.append(("pixabay", query))
        return [
            SimpleNamespace(
                url="https://cdn.pixabay.com/video/2026/07/28/77.mp4",
                source_info={
                    "asset_id": "77",
                    "source_page": "https://pixabay.com/videos/77/",
                },
            ),
        ]

    monkeypatch.setattr(
        discovery, "_stock_provider", lambda: ("pexels", pexels),
    )
    monkeypatch.setattr(
        discovery, "_secondary_stock_provider",
        lambda name: ("pixabay", pixabay),
    )
    monkeypatch.setattr(discovery, "_download_stock_clip", lambda *_: b"FAKE")
    monkeypatch.setattr(
        discovery, "import_editorial_material",
        lambda *a, **kw: (imported.append(kw) or "saved.mp4"),
    )
    result = discovery.discover_scene_media(
        "/unused", "task-id", subject="Instituições",
        scenes=[{"text": "Nas eleições as pessoas depositam votos"}],
        source_metadata={}, max_stills=0, max_clips=1, search_variants=True,
    )
    assert calls[:2] == [
        ("pexels", "elections voting ballot people"),
        ("pixabay", "elections voting ballot people"),
    ]
    assert imported[0]["asset_id"] == "pixabay:77"
    assert result["imported_count"] == 1
    assert result["search_requests"] == 2
    assert result["visually_verified"] is False


def test_alternative_phrasing_is_bounded_and_never_claims_visual_review(monkeypatch):
    queries = []
    monkeypatch.setattr(discovery, "_stock_provider", lambda: (
        "pexels", lambda query, *_: (queries.append(query) or []),
    ))
    monkeypatch.setattr(
        discovery, "_secondary_stock_provider", lambda _: (None, None),
    )
    report = discovery.discover_scene_media(
        "/unused", "task-id", subject="Instituições",
        scenes=[{"text": "O parlamento mantém instituições políticas"}],
        source_metadata={}, max_stills=0, max_clips=3, search_variants=True,
    )
    assert queries == [
        "parliament government institutions",
        "parliament interior",
        "government chamber",
    ]
    assert report["search_requests"] == 3
    assert report["imported_count"] == 0
    assert report["rights_verified"] is False
