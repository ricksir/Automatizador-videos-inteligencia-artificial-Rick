"""Deterministic source-video slices for Rick's opt-in scene renderer.

This module computes which *part of which real downloaded video* must play
during each narration scene. It never opens files or calls network services;
the caller must inspect video duration and size first with the normal reader.

All paths originate from the existing downloaded-video list, NOT from a
manifest-controlled path. It has no generic-material fallback.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

MAX_SOURCE_SLICES = 1200
MIN_SOURCE_SECONDS = Decimal("0.05")
EPSILON = Decimal("0.00001")


def _number(value: Any, name: str, *, positive: bool = True) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not number.is_finite() or (number <= 0 if positive else number < 0):
        raise ValueError(f"{name} must be finite and nonnegative")
    return number


def plan_source_slices(
    timeline: Mapping[str, Any],
    source_specs: Mapping[str, Mapping[str, Any]],
    *,
    clip_speed: float = 1.0,
    safety_tail_seconds: float = 0.1,
) -> list[dict[str, Any]]:
    """Expand a complete scene timeline into individually decodable slices.

    The final scene extends by a small safety tail because frame/codec rounding
    may otherwise leave a black flash at the end of the narration. FFmpeg
    trims the concatenation back to the original audio duration.

    Each \`source_specs[name]\` is measured and validated by the caller:
      {"file_path": absolute downloaded path, "duration_seconds": positive,
       "width": positive, "height": positive}

    A too-short source loops *only inside its assigned scene*. No unrelated
    source is silently substituted. This does not verify footage semantics.
    """
    if not isinstance(timeline, Mapping) or timeline.get("status") != "ready_metadata_only":
        raise ValueError("scene timeline must pass strict metadata preflight")
    segments = timeline.get("segments")
    if not isinstance(segments, list) or not segments or len(segments) > MAX_SOURCE_SLICES:
        raise ValueError("scene timeline must contain a bounded list of segments")
    if not isinstance(source_specs, Mapping):
        raise ValueError("source_specs must be a mapping")
    speed = _number(clip_speed, "clip_speed")
    tail = _number(safety_tail_seconds, "safety_tail_seconds", positive=False)
    if tail > Decimal("0.25"):
        raise ValueError("safety_tail_seconds must be at most 0.25 s")

    cursors: dict[str, Decimal] = {}
    output: list[dict[str, Any]] = []
    expected_start = Decimal(0)

    for index, segment in enumerate(segments):
        if not isinstance(segment, Mapping):
            raise ValueError("malformed scene segment")
        name = segment.get("source_file")
        if not isinstance(name, str) or name not in source_specs:
            raise ValueError("scene source not among downloaded and measured files")
        spec = source_specs[name]
        if not isinstance(spec, Mapping) or not isinstance(spec.get("file_path"), str) or not spec["file_path"]:
            raise ValueError("scene source has no resolved video path")
        length = _number(spec.get("duration_seconds"), "source duration")
        width = _number(spec.get("width"), "source width")
        height = _number(spec.get("height"), "source height")
        if length < MIN_SOURCE_SECONDS:
            raise ValueError("source video is too short for safe processing")

        start = _number(segment.get("start_seconds"), "scene start", positive=False)
        end = _number(segment.get("end_seconds"), "scene end")
        if abs(start - expected_start) > Decimal("0.0001") or end <= start:
            raise ValueError("scene timeline has a gap, overlap or zero duration")
        expected_start = end
        required = (end - start + (tail if index == len(segments) - 1 else 0)) * speed

        cursor = cursors.get(name, Decimal(0))
        # Remaining source frame budget may be tiny due to prior slicing.
        # Start from the beginning rather than producing unusable <50ms clips.
        while required > EPSILON:
            if length - cursor < MIN_SOURCE_SECONDS:
                cursor = Decimal(0)
            take = min(required, length - cursor)
            if take <= EPSILON:
                raise ValueError("cannot allocate source-video duration")
            output.append({
                "source_file": name,
                "file_path": spec["file_path"],
                "source_start_seconds": float(cursor),
                "source_end_seconds": float(cursor + take),
                "source_width": int(width),
                "source_height": int(height),
                "duration_seconds": float(take / speed),
                "scene_number": segment.get("scene_number"),
            })
            if len(output) > MAX_SOURCE_SLICES:
                raise ValueError("scene render would exceed maximum source slices")
            cursor += take
            required -= take
            if length - cursor < MIN_SOURCE_SECONDS:
                cursor = Decimal(0)
        cursors[name] = cursor

    duration = _number(timeline.get("duration_seconds"), "audio duration")
    if abs(expected_start - duration) > Decimal("0.0001"):
        raise ValueError("scene segments do not cover the audio")
    target = duration + tail
    scheduled = sum((Decimal(str(item["duration_seconds"])) for item in output), Decimal(0))
    if abs(scheduled - target) > Decimal("0.002"):
        raise ValueError("scene render source allocations are inconsistent")
    return output
