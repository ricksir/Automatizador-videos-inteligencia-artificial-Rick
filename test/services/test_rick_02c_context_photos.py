"""02C: contextual Wikimedia fallback (offline; no approvals or publishing)."""
from __future__ import annotations

from hashlib import sha256

import pytest

from app.services import (
    rick_commons_context as commons,
    rick_scene_photo_fallback as photos,
    rick_scene_discovery as discovery,
)


def _page(title, *, license_name="Public domain", copyrighted="false"):
    encoded = title.removeprefix("File:").replace(" ", "_")
    return {
        "ns": 6,
        "title": title,
        "imageinfo": [{
            "mime": "image/jpeg",
            "thumburl": (
                "https://upload.wikimedia.org/wikipedia/commons/"
                f"thumb/a/ab/{encoded}"
            ),
            "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{encoded}",
            "extmetadata": {
                "LicenseShortName": {"value": license_name},
                "Copyrighted": {"value": copyrighted},
                "NonFree": {"value": "false"},
                "Restrictions": {"value": ""},
            },
        }],
    }


def _asset(kind="institutions"):
    term = "parliament" if kind == "institutions" else "ballot"
    return {
        "title": f"File:{term.title()} chamber.jpg",
        "source_page": f"https://commons.wikimedia.org/wiki/File:{term.title()}_chamber.jpg",
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/a/ab/file.jpg",
        "license": "Public domain",
        "mime": "image/jpeg",
        "context_kind": kind,
        "context_keyword": term,
        "identity_verified": False,
        "rights_verified": False,
    }


def test_only_known_context_categories_are_allowed():
    assert commons.contextual_topics("institutions") == (
        "parliament", "congress",
    )
    assert commons.contextual_topics("general") == ()
    with pytest.raises(ValueError, match="inválida"):
        commons.find_contextual_commons_stills("general")


def test_commons_context_filters_title_and_licenses(monkeypatch):
    def search(params):
        assert params["gsrnamespace"] == "6"
        assert params["gsrlimit"] == "30"
        assert params["gsrsearch"].startswith("intitle:")
        return ([
            _page("File:Parliament chamber.jpg"),
            _page("File:Parliament modern poster.jpg"),
            _page("File:Parliament copyrighted.jpg", license_name="CC BY 4.0"),
            _page("File:Parliamentarian speaking.jpg"),
        ], {})
    monkeypatch.setattr(commons, "_commons_pages", search)
    found = commons.find_contextual_commons_stills(
        "institutions", max_results=4,
    )
    assert [item["title"] for item in found] == [
        "File:Parliament chamber.jpg",
    ]
    assert found[0]["license"] == "Public domain"
    assert found[0]["selection_basis"] == (
        "filename_context_word_and_pd_cc0_metadata"
    )
    assert found[0]["visually_verified"] is False
    assert found[0]["rights_verified"] is False


def test_substring_matching_does_not_accept_unrelated_file_title(monkeypatch):
    monkeypatch.setattr(
        commons, "_commons_pages",
        lambda params: ([_page("File:Facebooks logo.jpg")], {}),
    )
    assert commons.find_contextual_commons_stills("ideas") == []


def test_second_safe_query_is_attempted_when_first_fails(monkeypatch):
    queries = []
    def search(params):
        queries.append(params["gsrsearch"])
        if params["gsrsearch"] == "intitle:parliament":
            raise RuntimeError("temporary Commons error: secret")
        return ([_page("File:Congress chamber.jpg")], {})
    monkeypatch.setattr(commons, "_commons_pages", search)
    found = commons.find_contextual_commons_stills("institutions")
    assert queries == ["intitle:parliament", "intitle:congress"]
    assert len(found) == 1
    assert found[0]["context_keyword"] == "congress"


def test_two_search_failures_raise_sanitized_error(monkeypatch):
    monkeypatch.setattr(
        commons, "_commons_pages",
        lambda params: (_ for _ in ()).throw(
            RuntimeError("PRIVATE KEY DO NOT LEAK")
        ),
    )
    with pytest.raises(RuntimeError, match="Todas as pesquisas") as error:
        commons.find_contextual_commons_stills("institutions")
    assert "PRIVATE KEY" not in str(error.value)


def test_contextual_import_stores_provenance_and_scene_without_approval(
    monkeypatch,
):
    imported = []
    monkeypatch.setattr(
        photos, "find_contextual_commons_stills", lambda *a, **kw: [_asset()],
    )
    monkeypatch.setattr(
        photos, "download_commons_still", lambda *_: ("photo.jpg", b"fake"),
    )
    monkeypatch.setattr(
        photos, "import_editorial_material",
        lambda *a, **kw: (imported.append(kw) or "generated.mp4"),
    )
    original_ids = set()
    result = photos.discover_context_photos(
        "/unused", "task", subject="Ideias políticas",
        scenes=[{"text": "o parlamento e as instituições"}],
        priority_scene_numbers=[1], existing_asset_ids=original_ids,
    )
    assert result["imported_count"] == 1
    assert result["searched_contexts"] == ["institutions"]
    assert result["human_approved"] is False
    assert result["visual_content_verified"] is False
    assert result["rights_verified"] is False
    assert imported[0]["scene_number"] == 1
    assert imported[0]["search_term"] == "parliament government institutions"
    assert imported[0]["title"] == "File:Parliament chamber.jpg"
    assert "Public domain" in imported[0]["source_note"]
    assert imported[0]["asset_id"] in original_ids
    assert imported[0]["asset_id"].startswith("commons:")


def test_already_imported_commons_page_is_not_downloaded(monkeypatch):
    candidate = _asset()
    existing = {"commons:" + sha256(
        candidate["source_page"].encode("utf-8")
    ).hexdigest()[:40]}
    monkeypatch.setattr(
        photos, "find_contextual_commons_stills", lambda *a, **k: [candidate],
    )
    monkeypatch.setattr(
        photos, "download_commons_still",
        lambda *_: pytest.fail("must not redownload"),
    )
    report = photos.discover_context_photos(
        "/unused", "task", subject="Instituições",
        scenes=[{"text": "instituições e parlamento"}],
        priority_scene_numbers=[1], existing_asset_ids=existing,
    )
    assert report["imported_count"] == 0
    assert report["errors"] == []


def test_search_limits_imports_and_tries_each_context_once(monkeypatch):
    calls = []
    def search(kind, **kwargs):
        calls.append(kind)
        return [_asset(kind)]
    monkeypatch.setattr(photos, "find_contextual_commons_stills", search)
    monkeypatch.setattr(
        photos, "download_commons_still", lambda *_: ("photo.jpg", b"fake"),
    )
    monkeypatch.setattr(
        photos, "import_editorial_material", lambda *a, **kw: "photo.mp4",
    )
    report = photos.discover_context_photos(
        "/unused", "task", subject="Cidadania",
        scenes=[
            {"text": "as instituições e o parlamento"},
            {"text": "as instituições do congresso"},
            {"text": "nas eleições as urnas recebem votos"},
        ],
        priority_scene_numbers=[1, 2, 3],
        existing_asset_ids=set(), max_imports=2, max_searches=2,
    )
    assert report["imported_count"] == 2
    assert calls == ["institutions", "elections"]


def test_failed_commons_search_is_sanitized_and_other_contexts_continue(
    monkeypatch,
):
    def search(kind, **kwargs):
        if kind == "institutions":
            raise RuntimeError("SECRET API")
        return [_asset("elections")]
    monkeypatch.setattr(photos, "find_contextual_commons_stills", search)
    monkeypatch.setattr(
        photos, "download_commons_still", lambda *_: ("photo.jpg", b"fake"),
    )
    monkeypatch.setattr(
        photos, "import_editorial_material", lambda *a, **kw: "photo.mp4",
    )
    result = photos.discover_context_photos(
        "/unused", "task", subject="Democracia",
        scenes=[
            {"text": "instituições de governo"},
            {"text": "nas eleições há votação"},
        ],
        priority_scene_numbers=[1, 2], existing_asset_ids=set(),
    )
    assert result["imported_count"] == 1
    assert result["errors"][0]["code"] == "commons_search_failed"
    assert "SECRET" not in str(result)


def test_integrated_discovery_runs_context_fallback_only_with_explicit_flag(
    monkeypatch,
):
    called = []
    monkeypatch.setattr(
        discovery, "_stock_provider", lambda: (None, None),
    )
    monkeypatch.setattr(
        "app.services.rick_scene_photo_fallback.discover_context_photos",
        lambda *a, **kw: (
            called.append(kw) or {
                "imported_count": 1,
                "imported": [{
                    "file": "context.mp4", "media_kind": "context_photo",
                    "source_page": "https://commons.wikimedia.org/wiki/File:Ballot.jpg",
                }],
                "searched_contexts": ["elections"], "errors": [],
                "visual_content_verified": False, "rights_verified": False,
                "human_approved": False,
            }
        ),
    )
    scenes = [{"text": "Nas eleições brasileiras os votos são contados"}]
    args = dict(
        tasks_root="/unused", task_id="task",
        subject="Eleições no Brasil", scenes=scenes,
        source_metadata={}, max_stills=4, max_clips=0,
        priority_scene_numbers=[1],
    )
    before = discovery.discover_scene_media(**args)
    assert before["imported_count"] == 0
    assert called == []
    after = discovery.discover_scene_media(
        **args, search_context_photos=True,
    )
    assert len(called) == 1
    assert after["imported_count"] == 1
    assert after["context_photos"]["imported_count"] == 1
    assert after["rights_verified"] is False


def test_failed_context_import_does_not_approve_or_export(monkeypatch):
    monkeypatch.setattr(
        photos, "find_contextual_commons_stills", lambda *a, **kw: [_asset()],
    )
    monkeypatch.setattr(
        photos, "download_commons_still",
        lambda *_: (_ for _ in ()).throw(ValueError("invalid pixels")),
    )
    monkeypatch.setattr(
        photos, "import_editorial_material",
        lambda *a, **kw: pytest.fail("invalid image must not be imported"),
    )
    result = photos.discover_context_photos(
        "/unused", "task", subject="Instituições",
        scenes=[{"text": "instituições parlamentares"}],
        priority_scene_numbers=[1], existing_asset_ids=set(),
    )
    assert result["imported_count"] == 0
    assert result["errors"][0]["stage"] == "commons_import"
    assert result["human_approved"] is False
