"""Rick 02D: bounded, local pixel inspection, never semantic approval."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.services import rick_visual_media_audit as audit


def _file(folder: Path, name: str) -> str:
    path = folder / name
    path.write_bytes(b"not a real MP4 but enough to mock thumbnails")
    return str(path)


def _pattern(kind: str, second: bool = False) -> Image.Image:
    image = Image.new("L", (96, 96), 125)
    if kind == "black":
        return Image.new("L", (96, 96), 0)
    if kind == "white":
        return Image.new("L", (96, 96), 255)
    draw = ImageDraw.Draw(image)
    if kind == "center":
        draw.rectangle((15, 15, 80, 80), fill=30)
        if second:
            draw.rectangle((15, 15, 80, 80), fill=200)
    elif kind == "other":
        draw.rectangle((5, 5, 34, 34), fill=20)
    return image


def test_detects_probable_blank_and_static_without_claiming_semantics(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(
        audit, "_extract_gray_frame",
        lambda path, seconds: _pattern("black"),
    )
    report = audit.inspect_proposed_visuals(
        {"scenes": [{"primary": "clip.mp4"}]},
        {"clip.mp4": _file(tmp_path, "clip.mp4")},
    )
    assert report["attempted"] == 1
    assert report["inspected"] == 1
    assert report["possible_blank"] == 1
    assert "possibly_dark_or_blank" in report["files"][0]["flags"]
    assert "static_or_nearly_static" in report["files"][0]["flags"]
    assert report["semantic_content_verified"] is False
    assert report["rights_verified"] is False
    assert report["human_approved"] is False


def test_duplicate_visual_is_a_warning_and_does_not_change_proposals(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(
        audit, "_extract_gray_frame",
        lambda path, seconds: _pattern(
            "center" if path.name in ("a.mp4", "b.mp4") else "other",
            second=seconds > 0.5,
        ),
    )
    scenes = [
        {"scene_number": 1, "primary": "a.mp4", "human_approved": False},
        {"scene_number": 2, "primary": "b.mp4", "human_approved": False},
        {"scene_number": 3, "primary": "c.mp4", "human_approved": False},
    ]
    paths = {
        name: _file(tmp_path, name) for name in ("a.mp4", "b.mp4", "c.mp4")
    }
    report = audit.inspect_proposed_visuals({"scenes": scenes}, paths)
    assert report["files"][1]["similar_to"] == "a.mp4"
    assert "possibly_duplicate_visual" in report["files"][1]["flags"]
    assert report["possible_duplicates"] >= 1
    assert scenes[1]["primary"] == "b.mp4"
    assert scenes[1]["human_approved"] is False
    assert report["semantic_content_verified"] is False


def test_only_inventory_selected_files_are_opened(tmp_path, monkeypatch):
    inspected = []
    monkeypatch.setattr(
        audit, "_extract_gray_frame",
        lambda path, seconds: (
            inspected.append(path.name) or _pattern("center")
        ),
    )
    report = audit.inspect_proposed_visuals(
        {"scenes": [
            {"primary": "allowed.mp4"},
            {"primary": "../secret.mp4"},
            {"primary": "not-in-inventory.mp4"},
        ]},
        {"allowed.mp4": _file(tmp_path, "allowed.mp4")},
    )
    assert report["attempted"] == 1
    assert inspected == ["allowed.mp4", "allowed.mp4"]


def test_does_not_follow_symlink(tmp_path, monkeypatch):
    real = tmp_path / "real.mp4"
    real.write_bytes(b"dummy")
    link = tmp_path / "link.mp4"
    try:
        link.symlink_to(real)
    except (NotImplementedError, OSError):
        pytest.skip("Symlink unavailable")
    monkeypatch.setattr(
        audit, "_extract_gray_frame",
        lambda *_: pytest.fail("Must not read symlink"),
    )
    report = audit.inspect_proposed_visuals(
        {"scenes": [{"primary": "link.mp4"}]}, {"link.mp4": str(link)}
    )
    assert report["files"][0]["flags"] == ["file_not_eligible"]


def test_frame_extraction_failure_is_non_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(
        audit, "_extract_gray_frame",
        lambda path, seconds: (
            _pattern("center") if seconds < 0.5 else
            (_ for _ in ()).throw(subprocess.TimeoutExpired("ffmpeg", 15))
        ),
    )
    report = audit.inspect_proposed_visuals(
        {"scenes": [{"primary": "clip.mp4"}]},
        {"clip.mp4": _file(tmp_path, "clip.mp4")},
    )
    assert report["inspected"] == 1
    assert report["files"][0]["frames_read"] == 1
    assert "frame_extraction_failed" in report["files"][0]["flags"]
    assert "only_one_frame" in report["files"][0]["flags"]


def test_visual_audit_is_bounded_and_deduplicates_file_names(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(
        audit, "_extract_gray_frame",
        lambda path, seconds: _pattern("center"),
    )
    files = {f"f{i}.mp4": _file(tmp_path, f"f{i}.mp4") for i in range(5)}
    scenes = [{"primary": f"f{i}.mp4"} for i in [0, 0, 1, 2, 3, 4]]
    report = audit.inspect_proposed_visuals(
        {"scenes": scenes}, files, max_files=3,
    )
    assert report["attempted"] == 3
    assert report["not_inspected"] == 2
    assert len(report["files"]) == 3


@pytest.mark.parametrize("invalid_limit", [0, -1, 21, True])
def test_invalid_limits_are_rejected(invalid_limit):
    with pytest.raises(ValueError):
        audit.inspect_proposed_visuals(
            {"scenes": []}, {}, max_files=invalid_limit,
        )


def test_report_indicates_real_pixel_inspection_is_not_visual_semantic_qa():
    code = (
        Path(__file__).parents[2] / "webui" / "rick_editorial_panel.py"
    ).read_text(encoding="utf-8")
    assert "Inspeção local de quadros — indicadores técnicos" in code
    assert "Propostas completas por metadados:" in code
    assert "NÃO identifica pessoas, objetos" in code


def test_native_ffmpeg_extracts_a_small_local_video(tmp_path):
    from imageio_ffmpeg import get_ffmpeg_exe

    output = tmp_path / "test.mp4"
    subprocess.run([
        get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
        "-nostdin", "-y", "-f", "lavfi", "-i",
        "color=c=blue:s=96x160:r=10:d=2",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(output),
    ], check=True, timeout=30, stdout=subprocess.DEVNULL)
    frame = audit._extract_gray_frame(output, 0.3)
    assert frame.size == (96, 96)
    assert frame.mode == "L"
    report = audit.inspect_proposed_visuals(
        {"scenes": [{"primary": "test.mp4"}]},
        {"test.mp4": str(output)},
    )
    assert report["inspected"] == 1
