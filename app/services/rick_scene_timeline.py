"""Preflight of a scene-ordered render timeline (no media processing).

Convert the offline assignment preview from Rick 02B2A into deterministic,
precisely bounded instructions for a future optional MoviePy/FFmpeg renderer.
Do not silently substitute unrelated stock material for missing scenes.

A "ready" plan means only metadata consistency; the video file's content,
decodability, duration and relation to the narrator are NOT verified here.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import PurePath
from typing import Any, Mapping, Sequence

MAX_SCENES = 60
MAX_SEGMENTS = 1200
_ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
_EPSILON = Decimal("0.0001")


def _positive_seconds(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a positive finite duration")
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{label} must be a positive finite duration") from None
    if not numeric.is_finite() or numeric <= 0:
        raise ValueError(f"{label} must be a positive finite duration")
    return numeric


def _seconds(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite timestamp")
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{label} must be a finite timestamp") from None
    if not numeric.is_finite() or numeric < 0:
        raise ValueError(f"{label} must be a finite nonnegative timestamp")
    return numeric


def _filename(name: Any) -> str | None:
    if (
        not isinstance(name, str)
        or not name
        or "/" in name
        or "\\" in name
        or name in {".", ".."}
        or "\x00" in name
    ):
        return None
    if PurePath(name).suffix.lower() not in _ALLOWED_EXTENSIONS:
        return None
    return name


def _basename(path: str) -> str:
    # Accept either Windows or POSIX paths passed by the pipeline, without
    # inspecting the filesystem or potentially sensitive source URLs.
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def build_scene_render_preflight(
    candidate_preview: Mapping[str, Any],
    downloaded_files: Sequence[str],
    audio_seconds: float,
    *,
    max_clip_seconds: float = 4.0,
) -> dict[str, Any]:
    """Create an all-or-nothing, scene-exact metadata render timeline.

    If a scene is missing a valid candidate, or metadata is inconsistent,
    status is 'blocked' and segments is empty. No fallback to unrelated media.
    A 'ready_metadata_only' plan MUST still pass real media-duration/codec
    checks before handing segments to a renderer.
    """
    if not isinstance(candidate_preview, Mapping):
        raise ValueError("candidate_preview must be a record")
    scenes = candidate_preview.get("scenes")
    if not isinstance(scenes, list) or not (1 <= len(scenes) <= MAX_SCENES):
        raise ValueError("candidate_preview must contain 1..60 scenes")
    if isinstance(downloaded_files, (str, bytes)) or not isinstance(downloaded_files, Sequence):
        raise ValueError("downloaded_files must be an ordered sequence of paths")
    duration = _positive_seconds(audio_seconds, "audio_seconds")
    maximum = _positive_seconds(max_clip_seconds, "max_clip_seconds")
    file_names = [_basename(file) for file in downloaded_files if isinstance(file, str)]
    counts = Counter(file_names)
    segments: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    # Candidate previews remain supported. A preview carrying human-review
    # fields is subject to all-or-nothing approval; it must not revert to
    # search-term-only matching when some decisions are incomplete.
    has_editorial_review = any(
        isinstance(scene, Mapping) and "editorial_review" in scene
        for scene in scenes
    )
    if has_editorial_review and candidate_preview.get("status") != "ready_human_reviewed":
        blockers.append({"code": "editorial_review_incomplete", "scene_number": None})
    last_end = Decimal(0)
    last_name: str | None = None
    repeated_sources = 0

    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, Mapping):
            raise ValueError("every scene must be a record")
        start = _seconds(scene.get("start_seconds"), "scene.start_seconds")
        end = _positive_seconds(scene.get("end_seconds"), "scene.end_seconds")
        if abs(start - last_end) > _EPSILON:
            raise ValueError("scene timestamps have a gap or overlap")
        # Collapse minor rounding noise instead of leaving invisible gaps.
        start = last_end
        if end <= start:
            raise ValueError("every scene must have positive duration")
        last_end = end
        name = _filename(scene.get("assigned_material_file"))
        if scene.get("match_status") != "term_match_unverified":
            name = None
        if has_editorial_review and (
            scene.get("editorial_review") != "approved_by_human"
            or scene.get("editorial_rights_checked") is not True
            or scene.get("editorial_content_checked") is not True
            or not isinstance(scene.get("editorial_source_note"), str)
            or not scene["editorial_source_note"].strip()
        ):
            name = None

        if name is None:
            blockers.append({
                "code": "scene_missing_candidate",
                "scene_number": index,
            })
            continue
        if counts[name] != 1:
            blockers.append({
                "code": "scene_file_unavailable_or_ambiguous",
                "scene_number": index,
            })
            continue
        if name == last_name:
            repeated_sources += 1
        last_name = name

        cursor = start
        while cursor < end:
            next_boundary = min(cursor + maximum, end)
            segments.append({
                "scene_number": index,
                "source_file": name,
                "start_seconds": float(cursor),
                "end_seconds": float(next_boundary),
                "duration_seconds": float(next_boundary - cursor),
                "media_verified": False,
            })
            if len(segments) > MAX_SEGMENTS:
                raise ValueError("too many render segments")
            cursor = next_boundary

    if abs(last_end - duration) > _EPSILON:
        raise ValueError("scene plan duration differs from audio")
    if candidate_preview.get("scene_count", len(scenes)) != len(scenes):
        raise ValueError("scene_count does not match scene list")

    if blockers:
        segments = []
    warnings = [
        {
            "code": "scene_alignment_estimated",
            "message": "Cenas baseadas em estimativa, não em timestamps reais da fala.",
        },
        {
            "code": "scene_media_unverified",
            "message": "A presença do arquivo não comprova conteúdo, identidade ou duração reproduzível.",
        },
    ]
    if repeated_sources:
        warnings.append({
            "code": "scene_adjacent_source_reused",
            "count": repeated_sources,
        })
    return {
        "version": 1,
        "status": "blocked" if blockers else "ready_metadata_only",
        "duration_seconds": float(duration),
        "max_clip_seconds": float(maximum),
        "scene_count": len(scenes),
        "segment_count": len(segments),
        "segments": segments,
        "blockers": blockers,
        "warnings": warnings,
        "media_verified": False,
        "alignment": candidate_preview.get("alignment", "estimated"),
    }
