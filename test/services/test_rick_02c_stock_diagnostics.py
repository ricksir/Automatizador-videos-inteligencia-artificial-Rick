"""02C: bounded diagnostics and transient recovery; fully offline."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from app.services import material, rick_scene_discovery as discovery


def _response(status=200, body=None, content_type="application/json"):
    return SimpleNamespace(
        status_code=status,
        headers={"content-type": content_type},
        json=lambda: body,
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "rejected the API key"),
        (429, "rate limit exceeded"),
        (403, "search request failed"),
        (500, "search request failed"),
    ],
)
def test_material_search_logs_safe_http_diagnostics(status, expected):
    response = _response(status=status, body={"message": "sk-sensitive"})
    messages = []
    with patch.object(material.logger, "error", side_effect=messages.append):
        assert material._stock_search_results("pexels", response, "videos") is None
    assert any(expected in line for line in messages)
    assert "sk-sensitive" not in "\n".join(messages)


def test_material_search_handles_html_instead_of_json_without_leaking_body():
    def fail():
        raise ValueError("Sensitive body content with token=MY-API-KEY")
    response = _response(
        status=200, body=None, content_type="text/html",
    )
    response.json = fail
    messages = []
    with patch.object(material.logger, "error", side_effect=messages.append):
        assert material._stock_search_results("coverr", response, "hits") is None
    assert "non-JSON" in messages[0]
    assert "MY-API-KEY" not in messages[0]


def test_material_stock_results_accept_normal_pexels_and_coverr_payloads():
    assert material._stock_search_results(
        "pexels", _response(body={"videos": [{"id": 7}]}), "videos"
    ) == [{"id": 7}]
    assert material._stock_search_results(
        "coverr", _response(body={"hits": [{"id": 4}]}), "hits"
    ) == [{"id": 4}]


class FakeMP4Response:
    def __init__(self, status=200, data=b"0000ftyp0000good"):
        self.status_code = status
        self.headers = {"Content-Type": "video/mp4"}
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def iter_content(self, chunk_size):
        yield self.data


def test_transient_503_is_retried_on_same_https_url(monkeypatch):
    url = "https://videos.pexels.com/video-files/222/test.mp4"
    attempts = []
    responses = iter([FakeMP4Response(503), FakeMP4Response(200)])

    def get(uri, **kwargs):
        attempts.append((uri, kwargs))
        return next(responses)

    monkeypatch.setattr(discovery.requests, "get", get)
    monkeypatch.setattr(discovery.time, "sleep", lambda _: None)
    assert discovery._download_stock_clip(url)[4:8] == b"ftyp"
    assert len(attempts) == 2
    assert all(args["allow_redirects"] is False for _, args in attempts)
    assert all(uri == url for uri, _ in attempts)


def test_download_authentication_and_invalid_mp4_are_not_retried(monkeypatch):
    url = "https://videos.pexels.com/video-files/222/test.mp4"
    for response, reason in [
        (FakeMP4Response(403), "http_access_denied"),
        (FakeMP4Response(200, b"not a real video header"), "invalid_mp4_header"),
    ]:
        attempts = []
        monkeypatch.setattr(
            discovery.requests, "get",
            lambda uri, **kwargs: (attempts.append(uri) or response),
        )
        with pytest.raises(discovery.StockDownloadError) as exc:
            discovery._download_stock_clip(url)
        assert exc.value.code == reason
        assert len(attempts) == 1


def test_download_timeout_is_bounded_and_has_stable_code(monkeypatch):
    attempts = []
    def get(uri, **kwargs):
        attempts.append(uri)
        raise requests.Timeout("https://videos.pexels.com/key=private")
    monkeypatch.setattr(discovery.requests, "get", get)
    monkeypatch.setattr(discovery.time, "sleep", lambda _: None)
    with pytest.raises(discovery.StockDownloadError) as error:
        discovery._download_stock_clip(
            "https://videos.pexels.com/video-files/222/test.mp4"
        )
    assert error.value.code == "download_timeout"
    assert error.value.retryable is True
    assert len(attempts) == 3
    assert "private" not in str(error.value)


def test_discovery_continues_after_error_and_records_download_stage(monkeypatch):
    monkeypatch.setattr(
        discovery, "_stock_provider",
        lambda: (
            "pexels",
            lambda *_: [
                SimpleNamespace(
                    url="https://videos.pexels.com/video-files/12/c.mp4",
                    source_info={
                        "asset_id": "12",
                        "source_page": "https://www.pexels.com/video/12/",
                    },
                ),
            ],
        ),
    )
    monkeypatch.setattr(
        discovery, "_download_stock_clip",
        lambda *_: (_ for _ in ()).throw(
            discovery.StockDownloadError("invalid_mp4_header")
        ),
    )
    report = discovery.discover_scene_media(
        "/unused", "t1", subject="História",
        scenes=[{"text": "O protesto reuniu muitas pessoas nas ruas"}],
        source_metadata={}, max_stills=0, search_variants=False,
    )
    assert report["imported_count"] == 0
    assert report["failure_count"] == 1
    assert report["diagnostics"][0] == {
        "scene": 1,
        "intent": "demonstrations",
        "provider": "pexels",
        "stage": "download",
        "code": "invalid_mp4_header",
        "exception_type": "StockDownloadError",
        "retryable": False,
    }
    assert "download" in report["issues"][0]


def test_discovery_identifies_editorial_import_error_and_recovers(monkeypatch):
    candidates = [
        SimpleNamespace(
            url=f"https://videos.pexels.com/video-files/{n}/clip.mp4",
            source_info={
                "asset_id": str(n),
                "source_page": f"https://www.pexels.com/video/{n}/",
            },
        )
        for n in (11, 12)
    ]
    monkeypatch.setattr(discovery, "_stock_provider",
                        lambda: ("pexels", lambda *_: candidates))
    monkeypatch.setattr(discovery, "_download_stock_clip",
                        lambda _: b"0000ftyp0000good")
    saved = []
    def importing(*args, **kwargs):
        if kwargs["asset_id"] == "pexels:11":
            raise ValueError("Arquivo MP4 inválido ou acima do limite de 64 MB. key=PRIVATE")
        saved.append(kwargs["asset_id"])
        return "good.mp4"
    monkeypatch.setattr(discovery, "import_editorial_material", importing)
    report = discovery.discover_scene_media(
        "/unused", "t1", subject="História",
        scenes=[{"text": "O protesto reuniu muitas pessoas nas ruas"}],
        source_metadata={}, max_stills=0,
    )
    assert report["imported_count"] == 1
    assert saved == ["pexels:12"]
    assert report["failure_count"] == 1
    assert report["diagnostics"][0]["stage"] == "import"
    assert report["diagnostics"][0]["code"] == "invalid_mp4_import"
    assert "PRIVATE" not in str(report)


def test_search_valueerror_is_classified_without_raw_exception(monkeypatch):
    monkeypatch.setattr(
        discovery, "_stock_provider",
        lambda: ("pexels", lambda *_: (_ for _ in ()).throw(
            ValueError("api_key=PRIVATE_TOKEN")
        )),
    )
    report = discovery.discover_scene_media(
        "/unused", "t1", subject="História",
        scenes=[{"text": "O protesto reuniu muitas pessoas nas ruas"}],
        source_metadata={}, max_stills=0,
    )
    assert report["failure_count"] == 1
    assert report["diagnostics"][0]["stage"] == "search"
    assert report["diagnostics"][0]["code"] == "search_provider_exception"
    assert "PRIVATE_TOKEN" not in str(report)
