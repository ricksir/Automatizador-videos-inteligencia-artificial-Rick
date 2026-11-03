"""Bounded, local *pixel* quality indicators for Rick pre-curation.

No remote vision API, uploads, publishing, approvals, face identification,
semantic recognition or copyright conclusions. Two small FFmpeg thumbnails per
proposed source allow detecting blank frames and suspected duplicate visuals.
These are visual warning signals, NOT proof that footage matches narration.
"""
from __future__ import annotations

import io
import math
import subprocess
from collections.abc import Mapping
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

_MAX_FILES = 20
_MAX_FILE_BYTES = 192 * 1024 * 1024
_TIMES = (0.3, 1.2)
_THUMB = (96, 96)


def _extract_gray_frame(path: Path, seconds: float) -> Image.Image:
    """Read a resized frame via packaged FFmpeg; no file writes or network."""
    from imageio_ffmpeg import get_ffmpeg_exe

    proc = subprocess.run(
        [
            get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
            "-nostdin", "-ss", str(seconds), "-i", str(path),
            "-frames:v", "1",
            "-vf", "scale=96:96:force_original_aspect_ratio=decrease,"
                   "pad=96:96:(ow-iw)/2:(oh-ih)/2,format=gray",
            "-f", "image2pipe", "-vcodec", "png", "pipe:1",
        ],
        check=True, timeout=15, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if not 100 <= len(proc.stdout) <= 400_000:
        raise ValueError("frame_payload_invalid")
    with Image.open(io.BytesIO(proc.stdout)) as image:
        if image.size != _THUMB:
            raise ValueError("frame_dimensions_invalid")
        return image.convert("L").copy()


def _difference_hash(image: Image.Image) -> int:
    """64-bit image difference hash; grouping hint, not identity recognition."""
    small = image.resize((9, 8), Image.Resampling.BILINEAR)
    pixels = list(small.getdata())
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | int(
                pixels[y * 9 + x] > pixels[y * 9 + x + 1]
            )
    return bits


def inspect_proposed_visuals(
    proposals: Mapping, available_paths: Mapping[str, str],
    *, max_files: int = 20,
) -> dict:
    """Audit only chosen filenames from the trusted task inventory.

    Does not edit the proposal, modify media, approve clips or publish.
    Files outside the provided inventory are never opened.
    """
    if (
        not isinstance(proposals, Mapping)
        or not isinstance(available_paths, Mapping)
        or type(max_files) is not int
        or not 1 <= max_files <= _MAX_FILES
    ):
        raise ValueError("Visual audit inputs invalid")
    scenes = proposals.get("scenes")
    if not isinstance(scenes, list) or len(scenes) > 60:
        raise ValueError("Visual audit scenes invalid")

    selected: list[str] = []
    for scene in scenes:
        if not isinstance(scene, Mapping):
            continue
        name = scene.get("primary")
        if (
            isinstance(name, str)
            and name in available_paths
            and name not in selected
        ):
            selected.append(name)

    results: list[dict] = []
    baseline: list[tuple[str, int, float, float]] = []
    for name in selected[:max_files]:
        path = Path(available_paths[name])
        row = {
            "file": name,
            "status": "unavailable",
            "flags": [],
            "frames_read": 0,
            "motion_indicator": None,
            "similar_to": None,
        }
        if (
            not path.is_file() or path.is_symlink()
            or not 0 < path.stat().st_size <= _MAX_FILE_BYTES
        ):
            row["flags"].append("file_not_eligible")
            results.append(row)
            continue

        frames: list[Image.Image] = []
        for seconds in _TIMES:
            try:
                frames.append(_extract_gray_frame(path, seconds))
            except (OSError, ValueError, subprocess.SubprocessError):
                row["flags"].append("frame_extraction_failed")
        row["frames_read"] = len(frames)
        if not frames:
            results.append(row)
            continue

        row["status"] = "pixel_samples_inspected"
        first = frames[0]
        brightness, contrast = (
            ImageStat.Stat(first).mean[0],
            ImageStat.Stat(first).stddev[0],
        )
        if brightness < 10 and contrast < 8:
            row["flags"].append("possibly_dark_or_blank")
        elif brightness > 245 and contrast < 8:
            row["flags"].append("possibly_bright_or_blank")

        if len(frames) >= 2:
            difference = ImageStat.Stat(
                ImageChops.difference(first, frames[1])
            ).mean[0]
            row["motion_indicator"] = round(difference, 2)
            if difference < 1.5:
                row["flags"].append("static_or_nearly_static")
        else:
            row["flags"].append("only_one_frame")

        fingerprint = _difference_hash(first)
        for prior_name, prior_hash, prior_mean, prior_contrast in baseline:
            if (
                (fingerprint ^ prior_hash).bit_count() <= 4
                and abs(brightness - prior_mean) < 8
                and abs(contrast - prior_contrast) < 10
                and math.isfinite(brightness)
            ):
                row["similar_to"] = prior_name
                row["flags"].append("possibly_duplicate_visual")
                break
        baseline.append((name, fingerprint, brightness, contrast))
        results.append(row)

    return {
        "version": 1,
        "status": "local_pixel_quality_hints_only",
        "inspected": sum(
            row["status"] == "pixel_samples_inspected" for row in results
        ),
        "attempted": len(results),
        "not_inspected": max(0, len(selected) - len(results)),
        "possible_duplicates": sum(
            "possibly_duplicate_visual" in row["flags"] for row in results
        ),
        "possible_blank": sum(
            any(flag in row["flags"] for flag in (
                "possibly_dark_or_blank", "possibly_bright_or_blank"
            )) for row in results
        ),
        "files": results,
        "semantic_content_verified": False,
        "historical_identity_verified": False,
        "rights_verified": False,
        "human_approved": False,
        "note": (
            "Inspeção local de dois quadros por vídeo. Alertas de imagens "
            "escuras, estáticas ou visualmente parecidas não comprovam "
            "significado, correspondência com a narração, autenticidade "
            "histórica nem direitos de uso."
        ),
    }
