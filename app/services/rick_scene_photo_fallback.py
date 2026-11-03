"""Opt-in, bounded scene-context photograph imports from Wikimedia Commons.

Only specific editorial categories can trigger the search. The media is kept
as a proposal, converted locally to a 4-second MP4 and never auto-approved.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path

from app.services.rick_auto_commons import download_commons_still
from app.services.rick_commons_context import (
    contextual_topics, find_contextual_commons_stills,
)
from app.services.rick_editorial_assets import import_editorial_material
from app.services.rick_scene_precuration import scene_search_context


def discover_context_photos(
    tasks_root: str | Path,
    task_id: str,
    *,
    subject: str,
    scenes: Sequence[Mapping],
    priority_scene_numbers: Sequence[int],
    existing_asset_ids: set[str],
    max_imports: int = 6,
    max_searches: int = 6,
) -> dict:
    """Try each context once, prioritizing previously unresolved scenes.

    Every candidate must pass the underlying Commons CC0/public-domain,
    filename, MIME, host, image-size and pixel-count checks. Metadata does
    not prove visual correctness or publication rights in all jurisdictions.
    """
    if (
        not isinstance(scenes, (list, tuple))
        or not 1 <= len(scenes) <= 60
        or not isinstance(priority_scene_numbers, (list, tuple))
        or any(type(n) is not int or n < 1 or n > len(scenes)
               for n in priority_scene_numbers)
        or not isinstance(existing_asset_ids, set)
        or type(max_imports) is not int or not 0 <= max_imports <= 8
        or type(max_searches) is not int or not 0 <= max_searches <= 8
    ):
        raise ValueError("Parâmetros de fotografias contextuais inválidos.")
    imported: list[dict] = []
    errors: list[dict] = []
    attempts: list[str] = []
    scanned: set[str] = set()
    for scene_number in dict.fromkeys(priority_scene_numbers):
        if len(imported) >= max_imports or len(attempts) >= max_searches:
            break
        intent = scene_search_context(scenes, scene_number - 1, subject)
        kind = intent["kind"]
        if not contextual_topics(kind) or kind in scanned:
            continue
        scanned.add(kind)
        attempts.append(kind)
        try:
            found = find_contextual_commons_stills(kind, max_results=4)
        except (RuntimeError, ValueError, OSError):
            errors.append({
                "scene": scene_number, "intent": kind,
                "stage": "commons_search", "code": "commons_search_failed",
            })
            continue
        added_for_kind = 0
        for asset in found:
            if len(imported) >= max_imports or added_for_kind >= 2:
                break
            if not isinstance(asset, Mapping):
                continue
            page = asset.get("source_page")
            if not isinstance(page, str):
                continue
            asset_id = "commons:" + sha256(
                page.encode("utf-8")
            ).hexdigest()[:40]
            if asset_id in existing_asset_ids:
                continue
            try:
                name, data = download_commons_still(dict(asset))
                local_file = import_editorial_material(
                    tasks_root, task_id, name, data,
                    scene_number=scene_number,
                    source_note=(
                        f"Commons {page} | {asset.get('license', '')}"
                    )[:350],
                    search_term=intent["query"][:150],
                    title=str(asset.get("title") or "")[:150],
                    asset_id=asset_id,
                )
            except (RuntimeError, ValueError, OSError):
                errors.append({
                    "scene": scene_number, "intent": kind,
                    "stage": "commons_import", "code": "commons_import_failed",
                })
                continue
            existing_asset_ids.add(asset_id)
            imported.append({
                "file": local_file,
                "scene_number": scene_number,
                "context_kind": kind,
                "search_term": intent["query"],
                "media_kind": "context_photo",
                "source_page": page,
                "license_metadata": asset.get("license"),
                "visual_content_verified": False,
                "rights_verified": False,
            })
            added_for_kind += 1
    return {
        "imported_count": len(imported),
        "imported": imported,
        "searched_contexts": attempts,
        "errors": errors[:16],
        "visual_content_verified": False,
        "rights_verified": False,
        "human_approved": False,
    }
