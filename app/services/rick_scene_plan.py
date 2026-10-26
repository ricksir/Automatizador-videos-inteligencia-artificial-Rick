"""Deterministic, offline first-pass scene plan for Rick short-form videos.

This is not a subtitle aligner and does NOT verify that a stock clip depicts
its query. It allocates *estimated* time windows and ordered search terms so
later pipeline stages can explicitly validate scene-to-material coverage.
No network, filesystem access, model calls, provider credentials or imports
from the media pipeline occur here.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Any


MAX_SCENES = 60
MAX_TERMS = 40
_MIN_SECONDS = 0.05
_END_PUNCTUATION = re.compile(r'[.!?;:][\)\]\}"\u201d\u2019]*$')


def _words(script: str) -> list[str]:
    if not isinstance(script, str):
        raise ValueError("script must be text")
    # Preserve lexical punctuation and pt-BR accent marks; only collapse
    # whitespace to form reviewable scene snippets.
    return script.split()


def _boundaries(words: list[str], count: int) -> list[int]:
    """Produce strictly increasing word offsets near punctuation if possible."""
    positions = [0]
    for scene_no in range(1, count):
        left = positions[-1] + 1
        right = len(words) - (count - scene_no)
        ideal = round(len(words) * scene_no / count)
        preferred = [
            index
            for index in range(max(left, ideal - 3), min(right, ideal + 3) + 1)
            if _END_PUNCTUATION.search(words[index - 1])
        ]
        offset = min(preferred, key=lambda i: (abs(i - ideal), i)) if preferred else ideal
        positions.append(max(left, min(right, offset)))
    return positions + [len(words)]


def build_scene_plan(
    script: str,
    search_terms: Sequence[str],
    audio_seconds: float,
    *,
    target_clip_seconds: float = 4.0,
) -> dict[str, Any]:
    """Allocate approximate visual scenes against a measured audio duration.

    Output is JSON serializable. All ranges are half-open seconds [start,end),
    contiguous, and cover audio_seconds. Search terms are *suggestions*,
    never a promise that matching media exists or that source footage is genuine.
    """
    words = _words(script)
    if not words:
        raise ValueError("script must contain words")
    try:
        duration = float(audio_seconds)
        target = float(target_clip_seconds)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("durations must be finite positive numbers") from exc
    if not math.isfinite(duration) or duration < _MIN_SECONDS:
        raise ValueError("audio_seconds must be a finite positive duration")
    if not math.isfinite(target) or target <= 0:
        raise ValueError("target_clip_seconds must be finite and positive")
    if isinstance(search_terms, (str, bytes)) or not isinstance(search_terms, Sequence):
        raise ValueError("search_terms must be an ordered list of strings")
    if any(not isinstance(term, str) for term in search_terms):
        raise ValueError("search_terms must contain only strings")
    terms = list(dict.fromkeys(term.strip() for term in search_terms if term.strip()))
    terms = terms[:MAX_TERMS]
    scene_count = max(1, min(math.ceil(duration / target), len(words), MAX_SCENES))
    boundaries = _boundaries(words, scene_count)

    scenes: list[dict[str, Any]] = []
    for index in range(scene_count):
        first = boundaries[index]
        last = boundaries[index + 1]
        # Use original time precision for the plan; round only for the JSON
        # display, and set the final endpoint from the measured audio.
        start = round(duration * index / scene_count, 4)
        end = round(duration * (index + 1) / scene_count, 4)
        term_index = min(
            len(terms) - 1,
            int(((first + last) / 2 / len(words)) * len(terms)),
        ) if terms else None
        scenes.append({
            "number": index + 1,
            "start_seconds": start,
            "end_seconds": end,
            "text": " ".join(words[first:last]),
            "search_term": terms[term_index] if term_index is not None else None,
            "alignment": "estimated",
            "media_verified": False,
        })
    scenes[-1]["end_seconds"] = duration

    warnings = [{
        "code": "scene_timing_estimated",
        "message": "Os intervalos são estimados; não representam alinhamento real da fala.",
    }]
    if not terms:
        warnings.append({
            "code": "scene_search_terms_missing",
            "message": "Nenhuma palavra-chave foi fornecida para pesquisar as cenas.",
        })
    elif len(terms) < len(scenes):
        warnings.append({
            "code": "scene_terms_reused",
            "message": "Há menos consultas distintas do que cenas; algumas foram reutilizadas.",
        })

    return {
        "version": 1,
        "duration_seconds": duration,
        "target_clip_seconds": target,
        "alignment": "estimated",
        "source_media_verified": False,
        "scene_count": scene_count,
        "scenes": scenes,
        "warnings": warnings,
    }
