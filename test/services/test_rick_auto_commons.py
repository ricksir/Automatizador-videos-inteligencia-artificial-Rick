"""Offline tests for the optional Commons-powered Rick auto-render path."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from app.services import rick_auto_commons as commons
from app.services import rick_auto_movie as movie


def _candidate(title="File:Antonio Gramsci.jpg", *,
               license_name="Public domain", copyrighted="False",
               url="https://upload.wikimedia.org/wikipedia/commons/a/a1/Antonio_Gramsci.jpg"):
    return {
        "ns": 6, "title": title, "index": 1,
        "imageinfo": [{
            "mime": "image/jpeg",
            "url": url,
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Antonio_Gramsci.jpg",
            "extmetadata": {
                "LicenseShortName": {"value": license_name},
                "LicenseUrl": {
                    "value": "https://creativecommons.org/publicdomain/zero/1.0/"
                },
                "Copyrighted": {"value": copyrighted},
                "NonFree": {"value": "False"},
            },
        }],
    }


def test_commons_license_and_filename_filter_fail_closed():
    good = commons._eligible_image(_candidate(), "Gramsci")
    assert good is not None
    assert good["license_legally_verified"] is False
    assert good["identity_verified"] is False
    assert commons._eligible_image(_candidate(title="File:Waterfall.jpg"), "Gramsci") is None
    assert commons._eligible_image(
        _candidate(license_name="CC BY-SA 4.0"), "Gramsci"
    ) is None
    assert commons._eligible_image(
        _candidate(license_name="Public domain", copyrighted="True"), "Gramsci"
    ) is None
    assert commons._eligible_image(
        _candidate(url="https://unknown.example/a.jpg"), "Gramsci"
    ) is None
    danger = _candidate()
    danger["imageinfo"][0]["extmetadata"]["Restrictions"] = {"value": "personality"}
    assert commons._eligible_image(danger, "Gramsci") is None


def test_commons_cc0_needs_license_url_and_blocks_external_redirect():
    assert commons._eligible_image(
        _candidate(license_name="CC0 1.0", copyrighted="True"), "Gramsci"
    )
    candidate = _candidate(license_name="CC0 1.0", copyrighted="True")
    candidate["imageinfo"][0]["extmetadata"]["LicenseUrl"]["value"] = (
        "https://attacker.example/terms"
    )
    assert commons._eligible_image(candidate, "Gramsci") is None
    assert not commons._trusted_url(
        "https://upload.wikimedia.org.evil.test/wikipedia/commons/img.jpg",
        media=True,
    )
    assert not commons._trusted_url(
        "http://upload.wikimedia.org/wikipedia/commons/img.jpg", media=True
    )


def test_commons_search_uses_fixed_host_and_rejects_unrelated_files(monkeypatch):
    seen = []

    class Response:
        status_code = 200
        content = b'{"query":{"pages":[]}}'

        def raise_for_status(self):
            pass

        def json(self):
            return {"query": {"pages": [
                _candidate(title="File:Waterfall.jpg"),
                _candidate(),
            ]}}

    def fake_get(url, **kwargs):
        seen.append((url, kwargs))
        return Response()

    monkeypatch.setattr(commons.requests, "get", fake_get)
    matched = commons.find_commons_stills("Gramsci")
    assert len(matched) == 1
    assert matched[0]["title"] == "File:Antonio Gramsci.jpg"
    assert seen[0][0] == "https://commons.wikimedia.org/w/api.php"
    assert seen[0][1]["params"]["gsrnamespace"] == "6"
    assert seen[0][1]["allow_redirects"] is False


def test_commons_download_checks_actual_image(monkeypatch):
    image = Image.new("RGB", (16, 16))
    data = io.BytesIO()
    image.save(data, format="PNG")
    payload = data.getvalue()

    class Response:
        status_code = 200
        headers = {"Content-Type": "image/png"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield payload[:20]
            yield payload[20:]

    monkeypatch.setattr(commons.requests, "get", lambda *args, **kwargs: Response())
    name, downloaded = commons.download_commons_still({
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/a/b/file.png",
        "mime": "image/png",
    })
    assert name.endswith(".png")
    assert downloaded == payload


def _auto_task(tmp_path: Path):
    root = tmp_path / "tasks"
    folder = root / "task-123"
    folder.mkdir(parents=True)
    (folder / "audio.mp3").write_bytes(b"synthetic-audio")
    (folder / "original.mp4").write_bytes(b"original-immutable")
    (folder / "script.json").write_text(json.dumps({
        "params": {"subtitle_enabled": False, "video_clip_duration": 4},
        "script": "Gramsci estudou. Seu pensamento mudou a história.",
    }), encoding="utf-8")
    return root, folder


def test_auto_render_creates_separate_mp4_and_does_not_invent_approval(
    tmp_path, monkeypatch
):
    root, folder = _auto_task(tmp_path)
    paths = {}
    scenes = [
        {"start_seconds": 0.0, "end_seconds": 2.0,
         "search_term": "Gramsci theory", "text": "Gramsci estudou"},
        {"start_seconds": 2.0, "end_seconds": 4.0,
         "search_term": "Gramsci history", "text": "Mudou a história"},
    ]
    monkeypatch.setattr(movie, "load_review_workspace", lambda *a, **k: {
        "preview": {"scenes": scenes, "alignment": "estimated"},
        "paths": paths,
    })
    monkeypatch.setattr(movie.voice, "get_audio_duration", lambda _: 4.0)
    found = commons._eligible_image(_candidate(), "Gramsci")
    monkeypatch.setattr(movie, "find_commons_stills", lambda *a, **k: [found])
    monkeypatch.setattr(movie, "download_commons_still", lambda asset: (
        "image.jpg", b"FAKEBYTES"
    ))

    def fake_import(*args, **kwargs):
        imported = folder / "auto-source.mp4"
        imported.write_bytes(b"local-MP4")
        paths[imported.name] = str(imported)
        return imported.name

    monkeypatch.setattr(movie, "import_editorial_material", fake_import)
    plans = []

    def fake_combine(**kwargs):
        plans.append(kwargs["scene_timeline"])
        Path(kwargs["combined_video_path"]).write_bytes(b"COMBINED")

    def fake_generate(**kwargs):
        Path(kwargs["output_file"]).write_bytes(b"FINAL-MP4")
        return True

    monkeypatch.setattr(movie.video, "combine_videos", fake_combine)
    monkeypatch.setattr(movie.video, "generate_video", fake_generate)

    result = movie.export_auto_commons_video(
        root, "task-123", cache_dir=tmp_path,
        subject="O filósofo Gramsci e suas ideias",
    )
    assert result["status"] == "rendered_from_machine_screened_commons"
    assert result["human_reviewed"] is False
    assert result["rights_legally_verified"] is False
    assert result["scene_count"] == 2
    assert result["image_count"] == 1
    assert Path(result["output"]).read_bytes() == b"FINAL-MP4"
    assert Path(result["report"]).is_file()
    assert plans[0]["status"] == "ready_metadata_only"
    assert [segment["source_file"] for segment in plans[0]["segments"]] == [
        "auto-source.mp4", "auto-source.mp4",
    ]
    assert (folder / "original.mp4").read_bytes() == b"original-immutable"
    assert not (folder / "rick_editorial_review.json").exists()
    assert (folder / "script.json").is_file()


def test_auto_rejects_missing_license_without_generating(tmp_path, monkeypatch):
    root, folder = _auto_task(tmp_path)
    monkeypatch.setattr(movie, "load_review_workspace", lambda *a, **k: {
        "preview": {"scenes": [
            {"start_seconds": 0.0, "end_seconds": 4.0}
        ]},
        "paths": {},
    })
    monkeypatch.setattr(movie.voice, "get_audio_duration", lambda _: 4.0)
    monkeypatch.setattr(movie, "find_commons_stills", lambda *a, **k: [])
    with pytest.raises(ValueError, match="Commons não retornou"):
        movie.export_auto_commons_video(
            root, "task-123", cache_dir=tmp_path,
            subject="O filósofo Gramsci",
        )
    assert not (folder / "rick_auto_exports").exists()
    assert not (folder / "rick_editorial_review.json").exists()


def test_auto_does_not_run_without_historical_subject(tmp_path):
    root, folder = _auto_task(tmp_path)
    with pytest.raises(ValueError, match="pessoa histórica"):
        movie.export_auto_commons_video(
            root, "task-123", cache_dir=tmp_path,
            subject="Como funciona a natureza",
        )
    assert not (folder / "rick_auto_exports").exists()
