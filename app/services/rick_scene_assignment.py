"""Offline assignment preview: narration scene -> stock search term -> downloaded file.

The assignment is a *candidate* mapping based on exact normalized search terms,
not proof of semantic relevance, authenticity or actual render timing.
No provider, network, TTS, image recognition or paid calls are performed.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence


def _term_key(term: str) -> str:
    return " ".join(term.casefold().split())


def _safe_local_name(raw: Any) -> str | None:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        return None
    # Never take a manifest-controlled path as an instruction to read files.
    if "/" in raw or "\\" in raw or raw in {".", ".."}:
        return None
    return raw


def _source_identity(record: Mapping[str, Any], filename: str) -> str:
    provider = record.get("provider")
    asset_id = record.get("asset_id")
    if isinstance(provider, str) and isinstance(asset_id, (str, int)) and str(asset_id):
        return f"origin:{provider.casefold()}:{asset_id}"
    return f"file:{filename}"


def assign_scene_candidates(
    plan: Mapping[str, Any],
    material_sources: Sequence[Mapping[str, Any]],
    *,
    available_files: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build deterministic assignment diagnostics from the existing manifest.

    Only files included in available_files are considered when supplied.
    A scene with no exact search-term match stays unassigned; never fill it
    silently with semantically unrelated footage.
    """
    if not isinstance(plan, Mapping) or not isinstance(plan.get("scenes"), list):
        raise ValueError("expected a scene plan with a list of scenes")
    if isinstance(material_sources, (str, bytes)) or not isinstance(material_sources, Sequence):
        raise ValueError("material_sources must be a sequence of records")

    permitted: set[str] | None = None
    if available_files is not None:
        if isinstance(available_files, (str, bytes)) or not isinstance(available_files, Sequence):
            raise ValueError("available_files must be a sequence of filenames")
        permitted = {Path(item).name for item in available_files if isinstance(item, str)}

    by_term: dict[str, list[tuple[str, str]]] = defaultdict(list)
    seen_term_file: set[tuple[str, str]] = set()
    for record in material_sources:
        if not isinstance(record, Mapping):
            continue
        name = _safe_local_name(record.get("local_file"))
        term = record.get("search_term")
        if not name or not isinstance(term, str) or not term.strip():
            continue
        if permitted is not None and name not in permitted:
            continue
        key = _term_key(term)
        pair = (key, name)
        if pair in seen_term_file:
            continue
        seen_term_file.add(pair)
        by_term[key].append((name, _source_identity(record, name)))

    usage: dict[str, int] = defaultdict(int)
    previous_source: str | None = None
    scenes: list[dict[str, Any]] = []
    matched = missing = reused = 0
    for scene in plan["scenes"]:
        if not isinstance(scene, Mapping):
            raise ValueError("each scene must be a record")
        query = scene.get("search_term")
        key = _term_key(query) if isinstance(query, str) else ""
        options = by_term.get(key, []) if key else []
        chosen: tuple[str, str] | None = None
        was_reused = False
        if options:
            # Prefer an unused origin, avoid consecutive same-source scenes,
            # and break ties in the provider/manifest order. No randomness.
            indexed = list(enumerate(options))
            _, chosen = min(
                indexed,
                key=lambda item: (
                    usage[item[1][1]] > 0,
                    item[1][1] == previous_source,
                    usage[item[1][1]],
                    item[0],
                ),
            )
            was_reused = usage[chosen[1]] > 0
            usage[chosen[1]] += 1
            previous_source = chosen[1]
            matched += 1
            reused += int(was_reused)
        else:
            missing += 1

        # The record is reviewable, not footage verification.
        scenes.append({
            **scene,
            "assigned_material_file": chosen[0] if chosen else None,
            "candidate_count": len(options),
            "match_status": "term_match_unverified" if chosen else "missing_term_match",
            "material_reused": was_reused,
            "media_verified": False,
        })

    warnings: list[dict[str, str]] = []
    if missing:
        warnings.append({
            "code": "scene_media_missing",
            "message": f"{missing} cenas sem material correspondente à consulta de busca.",
        })
    if reused:
        warnings.append({
            "code": "scene_media_reused",
            "message": f"{reused} cenas reutilizam origens por falta de alternativas.",
        })
    warnings.append({
        "code": "scene_preview_only",
        "message": "Prévia por consulta: a seleção ainda não controla a montagem nem comprova o conteúdo da mídia.",
    })

    return {
        "version": 1,
        "status": "preview_only_not_rendered",
        "alignment": plan.get("alignment", "estimated"),
        "scene_count": len(scenes),
        "scenes_with_term_candidate": matched,
        "scenes_without_term_candidate": missing,
        "scenes_reusing_source": reused,
        "distinct_sources_used": len(usage),
        "scenes": scenes,
        "warnings": warnings,
    }
