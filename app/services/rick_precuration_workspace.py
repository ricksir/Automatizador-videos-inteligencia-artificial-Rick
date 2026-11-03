"""Persisted Rick scene-specific pre-curation proposals, never approvals.

Offline metadata suggestions are available on every review. Explicit
discovery may add Commons stills and context-specific stock clips. All saved
proposals are tied to the unmodified scene-preview fingerprint and current
inventory, so old choices cannot silently survive changes.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from app.services.rick_editorial_workspace import load_review_workspace, task_folder
from app.services.rick_scene_precuration import build_precuration

_FILENAME = "rick_scene_precuration.json"
_MAX_DOCUMENT = 250_000


def _inventory_signature(workspace: dict) -> str:
    records = []
    for name, path in sorted(workspace["paths"].items()):
        item = Path(path)
        if not item.is_file() or item.is_symlink():
            continue
        stat = item.stat()
        records.append([
            name, stat.st_size, stat.st_mtime_ns,
            workspace["source_metadata"].get(name, {}),
        ])
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_precuration(
    tasks_root: str | Path, task_id: str, workspace: dict,
) -> dict | None:
    folder = task_folder(tasks_root, task_id)
    file = folder / _FILENAME
    if not file.exists():
        return None
    if file.is_symlink() or not file.is_file() or file.stat().st_size > _MAX_DOCUMENT:
        raise ValueError("Registro de pré-curadoria inválido.")
    try:
        content = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ValueError("Pré-curadoria não pode ser recuperada.") from exc
    if (
        not isinstance(content, dict)
        or content.get("version") != 1
        or content.get("preview_sha256") != workspace["preview_sha256"]
        or content.get("inventory_sha256") != _inventory_signature(workspace)
        or not isinstance(content.get("report"), dict)
    ):
        return None
    return content["report"]


def run_scene_precuration(
    tasks_root: str | Path,
    task_id: str,
    state_materials: list[str],
    *,
    subject: str,
    audio_duration: object = None,
    cache_dir: str | Path | None = None,
    discover: bool = False,
) -> dict:
    if not isinstance(subject, str) or len(subject) > 500:
        raise ValueError("Assunto de pré-curadoria inválido.")
    workspace = load_review_workspace(
        tasks_root, task_id, state_materials,
        audio_duration=audio_duration, cache_dir=cache_dir,
    )
    discovery = None
    if discover:
        from app.services.rick_scene_discovery import discover_scene_media

        initial = build_precuration(
            subject, workspace["preview"]["scenes"],
            workspace["source_metadata"], list(workspace["paths"]),
        )
        # Spend the bounded media-search budget on unresolved scenes first,
        # then on existing but weak metadata candidates.
        priority = [
            row["scene_number"] for row in initial["scenes"]
            if not row["primary"]
        ] + [
            row["scene_number"] for row in initial["scenes"]
            if row["primary"] and row["metadata_score"] < 60
        ]
        discovery = discover_scene_media(
            tasks_root, task_id, subject=subject,
            scenes=workspace["preview"]["scenes"],
            source_metadata=workspace["source_metadata"],
            priority_scene_numbers=priority,
            search_variants=True,
            search_context_photos=True,
        )
        workspace = load_review_workspace(
            tasks_root, task_id, state_materials,
            audio_duration=audio_duration, cache_dir=cache_dir,
        )

    report = build_precuration(
        subject, workspace["preview"]["scenes"],
        workspace["source_metadata"], list(workspace["paths"]),
    )
    if discovery is not None:
        report["discovery"] = discovery
    document = {
        "version": 1,
        "preview_sha256": workspace["preview_sha256"],
        "inventory_sha256": _inventory_signature(workspace),
        "report": report,
        "note": (
            "SUGESTÃO NÃO APROVADA: pontuação por metadados, sem "
            "identificação visual, auditoria jurídica ou publicação."
        ),
    }
    folder = task_folder(tasks_root, task_id)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=folder, prefix=".rick-curation-",
            suffix=".tmp", delete=False,
        ) as file:
            temp = Path(file.name)
            json.dump(document, file, ensure_ascii=False, indent=2)
        if temp.stat().st_size > _MAX_DOCUMENT:
            raise ValueError("Relatório de pré-curadoria excede o tamanho permitido.")
        os.replace(temp, folder / _FILENAME)
        temp = None
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return report
