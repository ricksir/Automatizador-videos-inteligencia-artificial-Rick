"""Rick 02C: safe lower-resolution recovery for oversized free-stock clips.

All network, task storage and FFmpeg operations are mocked; no credentials,
provider usage, media writes, human approvals or publishing.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.schema import VideoAspect
from app.services import material, rick_scene_discovery as discovery


def test_pixabay_exposes_smaller_vertical_variants_without_changing_primary(monkeypatch):
    monkeypatch.setattr(material, "get_api_key", lambda _: "mock-api-key")
    versions = {
        "large": {
            "url": "https://cdn.pixabay.com/video/111/large.mp4",
            "width": 2160, "height": 3840, "size": 120 * 1024 * 1024,
        },
        "medium": {
            "url": "https://cdn.pixabay.com/video/111/medium.mp4",
            "width": 720, "height": 1280, "size": 12 * 1024 * 1024,
        },
        "small": {
            "url": "https://cdn.pixabay.com/video/111/small.mp4",
            "width": 480, "height": 854, "size": 4 * 1024 * 1024,
        },
        "tiny": {
            "url": "https://cdn.pixabay.com/video/111/tiny.mp4",
            "width": 240, "height": 426, "size": 1 * 1024 * 1024,
        },
        "horizontal": {
            "url": "https://cdn.pixabay.com/video/111/wrong.mp4",
            "width": 1280, "height": 720, "size": 3 * 1024 * 1024,
        },
    }
    response = SimpleNamespace(
        status_code=200,
        headers={"content-type": "application/json"},
        json=lambda: {"hits": [{
            "id": 111, "duration": 8, "pageURL": "https://pixabay.com/videos/111/",
            "videos": versions,
        }]},
    )
    monkeypatch.setattr(material.requests, "get", lambda *a, **k: response)
    found = material.search_videos_pixabay(
        "peaceful demonstration", 3, VideoAspect.portrait,
    )
    assert len(found) == 1
    # Existing video-generation pipeline retains its original choice.
    assert found[0].url == versions["large"]["url"]
    variants = found[0].source_info["editorial_rendition_alternatives"]
    assert [v["url"] for v in variants] == [
        versions["medium"]["url"], versions["small"]["url"],
    ]
    assert variants[0]["size_bytes"] == 12 * 1024 * 1024


def test_pexels_exposes_alternative_vertical_renditions():
    versions = [
        {"link": "https://videos.pexels.com/video-files/1/large.mp4",
         "width": 1080, "height": 1920, "file_size": 90 * 1024 * 1024},
        {"link": "https://videos.pexels.com/video-files/1/medium.mp4",
         "width": 720, "height": 1280, "file_size": 15 * 1024 * 1024},
        {"link": "https://videos.pexels.com/video-files/1/wrong.mp4",
         "width": 1280, "height": 720, "file_size": 10 * 1024 * 1024},
    ]
    options = material._editorial_rendition_alternatives(
        versions, versions[0]["link"], VideoAspect.portrait,
        url_key="link", size_key="file_size",
    )
    assert len(options) == 1
    assert options[0]["url"] == versions[1]["link"]


def _candidate(primary=None, alternatives=None):
    primary = primary or "https://cdn.pixabay.com/video/111/large.mp4"
    return SimpleNamespace(
        url=primary,
        source_info={
            "asset_id": "111",
            "source_page": "https://pixabay.com/videos/111/",
            "editorial_rendition_alternatives": alternatives or [
                {"url": "https://cdn.pixabay.com/video/111/medium.mp4",
                 "width": 720, "height": 1280, "size_bytes": 4 * 1024 * 1024},
            ],
        },
    )


def _discover(monkeypatch, candidates):
    monkeypatch.setattr(
        discovery, "_stock_provider", lambda: ("pixabay", lambda *_: candidates),
    )
    return discovery.discover_scene_media(
        "/unused", "task", subject="Civil society",
        scenes=[{"text": "Manifestação pacífica em praça pública"}],
        source_metadata={}, max_stills=0, search_variants=False,
    )


def test_oversized_primary_recovers_with_smaller_published_rendition(monkeypatch):
    requests = []
    writes = []
    def fake_download(url):
        requests.append(url)
        if url.endswith("large.mp4"):
            raise discovery.StockDownloadError("video_too_large")
        return b"0000ftyp0000good"
    monkeypatch.setattr(discovery, "_download_stock_clip", fake_download)
    monkeypatch.setattr(
        discovery, "import_editorial_material",
        lambda *a, **kw: (writes.append(kw) or "saved.mp4"),
    )
    report = _discover(monkeypatch, [_candidate()])
    assert report["imported_count"] == 1
    assert report["oversized_primaries_recovered"] == 1
    assert report["smaller_renditions_used"] == 1
    assert report["failure_count"] == 0
    assert requests == [
        "https://cdn.pixabay.com/video/111/large.mp4",
        "https://cdn.pixabay.com/video/111/medium.mp4",
    ]
    assert writes[0]["asset_id"] == "pixabay:111"
    assert report["rights_verified"] is False
    assert report["visually_verified"] is False


def test_unsafe_or_oversized_alternatives_are_not_downloaded(monkeypatch):
    attempts = []
    monkeypatch.setattr(
        discovery, "_download_stock_clip",
        lambda url: (
            attempts.append(url),
            (_ for _ in ()).throw(discovery.StockDownloadError("video_too_large")),
        )[1],
    )
    monkeypatch.setattr(
        discovery, "import_editorial_material",
        lambda *args, **kwargs: pytest.fail("should never import"),
    )
    candidate = _candidate(alternatives=[
        {"url": "https://cdn.pixabay.com.evil.test/video/1.mp4",
         "width": 720, "height": 1280, "size_bytes": 1000},
        {"url": "https://cdn.pixabay.com/video/1/oversize.mp4",
         "width": 720, "height": 1280, "size_bytes": 70 * 1024 * 1024},
        {"url": "https://cdn.pixabay.com/video/1/tiny.mp4",
         "width": 180, "height": 320, "size_bytes": 1000},
    ])
    report = _discover(monkeypatch, [candidate])
    assert attempts == [candidate.url]
    assert report["imported_count"] == 0
    assert report["failure_count"] == 1
    assert report["diagnostics"][0]["code"] == "video_too_large"


def test_all_variants_oversized_preserves_reason_and_never_approves(monkeypatch):
    monkeypatch.setattr(
        discovery, "_download_stock_clip",
        lambda url: (_ for _ in ()).throw(
            discovery.StockDownloadError("video_too_large")
        ),
    )
    monkeypatch.setattr(
        discovery, "import_editorial_material",
        lambda *args, **kwargs: pytest.fail("no valid video"),
    )
    report = _discover(monkeypatch, [_candidate()])
    assert report["failure_count"] == 1
    assert report["diagnostics"][0]["code"] == "video_too_large"
    assert report["oversized_primaries_recovered"] == 0
    assert report["imported_count"] == 0


def test_no_fallback_for_access_denied(monkeypatch):
    attempts = []
    def deny(url):
        attempts.append(url)
        raise discovery.StockDownloadError("http_access_denied")
    monkeypatch.setattr(discovery, "_download_stock_clip", deny)
    report = _discover(monkeypatch, [_candidate()])
    assert len(attempts) == 1
    assert report["failure_count"] == 1
    assert report["diagnostics"][0]["code"] == "http_access_denied"
