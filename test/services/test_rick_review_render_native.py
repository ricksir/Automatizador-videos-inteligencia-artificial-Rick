"""Opt-in REAL MoviePy/FFmpeg export of two offline synthetic Rick scenes.

Enable with RICK_RUN_NATIVE_RENDER_TEST=1. No remote, TTS, stock provider,
publish action or mocked media renderer is used.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from imageio_ffmpeg import get_ffmpeg_exe

from app.models.schema import VideoAspect
from app.services.voice import get_audio_duration
from app.services.rick_editorial_workspace import (
    load_review_workspace,
    save_editorial_workspace_review,
)
from app.services.rick_review_render import export_reviewed_video


def _run_ffmpeg(*args: str) -> bytes:
    result = subprocess.run(
        [get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin",
         *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return result.stdout


def _synthetic_video(path: Path, color: str) -> None:
    _run_ffmpeg(
        "-f", "lavfi", "-i", f"color=c={color}:s=144x256:r=12:d=4.5",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(path),
    )


def _read_frame_color(path: Path, seconds: float) -> tuple[int, int, int]:
    pixels = _run_ffmpeg(
        "-ss", f"{seconds:.3f}", "-i", str(path),
        "-vf", "scale=1:1", "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    )
    assert len(pixels) == 3, "Expected one RGB pixel from decoded MP4"
    return tuple(pixels)


def test_two_real_scenes_export_offline_with_correct_codecs_and_order(
    tmp_path: Path, monkeypatch
):
    if os.environ.get("RICK_RUN_NATIVE_RENDER_TEST") != "1":
        pytest.skip("Enable the real media test explicitly")
    probe = shutil.which("ffprobe")
    if probe is None:
        pytest.skip("FFprobe is required for native codec/duration verification")

    # Reduce only test-frame dimensions for fast CI. Real MoviePy/FFmpeg
    # combine_videos() and generate_video() must execute without mocks.
    monkeypatch.setattr(VideoAspect, "to_resolution", lambda self: (144, 256))

    root = tmp_path / "tasks"
    folder = root / "native-two-scenes"
    folder.mkdir(parents=True)
    cache = tmp_path / "trusted-video-cache"
    cache.mkdir()
    red = cache / "red.mp4"
    blue = cache / "blue.mp4"
    _synthetic_video(red, "red")
    _synthetic_video(blue, "blue")
    audio = folder / "audio.mp3"
    _run_ffmpeg(
        "-f", "lavfi", "-i", "sine=frequency=440:duration=4.0",
        "-vn", "-c:a", "libmp3lame", "-q:a", "5", "-y", str(audio),
    )
    duration = float(get_audio_duration(str(audio)))
    assert 3.7 <= duration <= 4.4
    middle = round(duration / 2, 5)

    manifest = {
        "script": "A primeira cena é vermelha. A segunda é azul.",
        "params": {
            "video_subject": "Duas cenas locais",
            "video_clip_duration": 4,
            "subtitle_enabled": False,
        },
        "rick_scene_candidate_preview": {
            "scene_count": 2,
            "status": "preview_only_not_rendered",
            "alignment": "estimated",
            "scenes": [
                {
                    "scene_number": 1,
                    "start_seconds": 0,
                    "end_seconds": middle,
                    "text": "Cena vermelha",
                    "search_term": "red",
                    "assigned_material_file": "red.mp4",
                    "match_status": "term_match_unverified",
                },
                {
                    "scene_number": 2,
                    "start_seconds": middle,
                    "end_seconds": duration,
                    "text": "Cena azul",
                    "search_term": "blue",
                    "assigned_material_file": "blue.mp4",
                    "match_status": "term_match_unverified",
                },
            ],
        },
        "material_sources": [
            {"local_file": "red.mp4", "provider": "local-test", "search_term": "red"},
            {"local_file": "blue.mp4", "provider": "local-test", "search_term": "blue"},
        ],
    }
    script = folder / "script.json"
    script.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    original = folder / "original.mp4"
    original.write_bytes(b"ORIGINAL-DO-NOT-CHANGE")
    originals = {file: file.read_bytes() for file in (red, blue, audio, script, original)}

    workspace = load_review_workspace(root, "native-two-scenes", [], cache_dir=cache)
    assert workspace["saved_review"] is None
    review = save_editorial_workspace_review(
        root, "native-two-scenes", workspace["preview_sha256"],
        [str(red), str(blue)],
        [
            {
                "scene_number": index,
                "decision": "approve",
                "selected_file": file.name,
                "source_note": "Sintético local; revisão humana declarada pelo teste",
                "content_checked": True,
                "rights_checked": True,
            }
            for index, file in enumerate((red, blue), 1)
        ],
        cache_dir=cache,
    )
    assert review["status"] == "ready_human_reviewed"
    result = export_reviewed_video(root, "native-two-scenes", cache_dir=cache)
    final = Path(result["output"])
    report = Path(result["report"])
    assert final.is_file() and final.stat().st_size > 0
    assert report.is_file()
    assert result["used_source_basenames"] == ["red.mp4", "blue.mp4"]

    probe_output = subprocess.run(
        [probe, "-v", "error", "-show_entries",
         "stream=codec_name,codec_type:format=duration",
         "-of", "json", str(final)],
        check=True, capture_output=True, text=True, timeout=30,
    )
    details = json.loads(probe_output.stdout)
    codecs = {
        item["codec_type"]: item["codec_name"] for item in details["streams"]
    }
    assert codecs["video"] == "h264"
    assert codecs["audio"] == "aac"
    final_duration = float(details["format"]["duration"])
    assert abs(final_duration - duration) < 0.35
    first = _read_frame_color(final, duration * 0.25)
    second = _read_frame_color(final, duration * 0.75)
    assert first[0] > first[2] + 70, f"Scene 1 not red: {first}"
    assert second[2] > second[0] + 70, f"Scene 2 not blue: {second}"
    assert all(file.read_bytes() == before for file, before in originals.items())
