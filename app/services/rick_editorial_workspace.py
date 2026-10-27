"""Local-only, read-only-by-default workspace for human scene reviews.

This module discovers already-downloaded files from the task state/manifest,
stores an optional editorial decision artifact, and NEVER renders or publishes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services.rick_editorial_review import build_editorial_review

_TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".webm", ".avi"})
_REVIEW_FILE = "rick_editorial_review.json"
_MAX_SCRIPT_BYTES = 4 * 1024 * 1024


def task_folder(tasks_root: str | Path, task_id: str) -> Path:
    """Resolve a child task directory; reject traversal and symlink exits."""
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise ValueError("Identificador de tarefa inválido.")
    root = Path(tasks_root).resolve()
    folder = root / task_id
    if folder.is_symlink() or not folder.is_dir() or folder.resolve().parent != root:
        raise ValueError("Tarefa indisponível ou fora da pasta autorizada.")
    return folder


def _script_data(folder: Path) -> dict[str, Any]:
    source = folder / "script.json"
    if not source.is_file() or source.is_symlink():
        raise ValueError("Esta tarefa não possui script.json válido.")
    if source.stat().st_size > _MAX_SCRIPT_BYTES:
        raise ValueError("Manifesto de tarefa excede o limite de leitura.")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Não foi possível ler a prévia desta tarefa.") from exc
    if not isinstance(data, dict):
        raise ValueError("Manifesto de tarefa inválido.")
    return data


def _preview_fingerprint(preview: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        preview, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def available_material_paths(
    material_sources: Sequence[Mapping[str, Any]],
    state_materials: Sequence[str],
) -> dict[str, str]:
    """Return unambiguous EXISTING video paths listed in BOTH data sources.

    The manifest's local_file is never treated as an OS path.
    The actual path is taken only from the application's task state.
    """
    if (not isinstance(material_sources, list)
            or not isinstance(state_materials, list)):
        return {}
    allowed_names = {
        item.get("local_file")
        for item in material_sources if isinstance(item, Mapping)
        and isinstance(item.get("local_file"), str)
        and item["local_file"] not in {".", ".."}
        and "/" not in item["local_file"] and "\\" not in item["local_file"]
        and "\x00" not in item["local_file"]
        and Path(item["local_file"]).suffix.lower() in _EXTENSIONS
    }
    safe_paths: list[Path] = []
    for raw in state_materials[:250]:
        if not isinstance(raw, str) or not raw:
            continue
        p = Path(raw)
        try:
            if (
                p.name in allowed_names
                and p.suffix.lower() in _EXTENSIONS
                and p.is_file()
                and not p.is_symlink()
            ):
                safe_paths.append(p)
        except OSError:
            continue
    counts = Counter(p.name for p in safe_paths)
    return {
        p.name: str(p.resolve())
        for p in safe_paths
        if counts[p.name] == 1
    }


def load_review_workspace(
    tasks_root: str | Path, task_id: str, state_materials: Sequence[str]
) -> dict[str, Any]:
    folder = task_folder(tasks_root, task_id)
    manifest = _script_data(folder)
    preview = manifest.get("rick_scene_candidate_preview")
    if not isinstance(preview, dict):
        raise ValueError(
            "Tarefa sem prévia por cena. Habilite 'Ajustar imagens à ordem do roteiro' "
            "e gere uma nova tarefa com materiais de banco."
        )
    scenes = preview.get("scenes")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 60:
        raise ValueError("Prévia de cenas inválida.")
    paths = available_material_paths(
        manifest.get("material_sources", []), state_materials
    )
    stored = None
    review_path = folder / _REVIEW_FILE
    if review_path.is_file() and not review_path.is_symlink():
        try:
            saved = json.loads(review_path.read_text(encoding="utf-8"))
            if (isinstance(saved, dict)
                    and saved.get("preview_sha256") == _preview_fingerprint(preview)
                    and isinstance(saved.get("review"), dict)):
                stored = saved["review"]
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    source_metadata = {}
    for record in manifest.get("material_sources", []):
        if not isinstance(record, dict):
            continue
        name = record.get("local_file")
        if name in paths and name not in source_metadata:
            source_metadata[name] = {
                "provider": str(record.get("provider") or "não informado")[:80],
                "source_page": str(record.get("source_page") or "")[:400],
            }
    return {
        "task_id": task_id,
        "task_dir": str(folder),
        "source_metadata": source_metadata,
        "preview": preview,
        "paths": paths,
        "saved_review": stored,
        "preview_sha256": _preview_fingerprint(preview),
    }


def save_editorial_workspace_review(
    tasks_root: str | Path,
    task_id: str,
    preview_sha256: str,
    downloaded_files: Sequence[str],
    decisions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Revalidate against the CURRENT preview before atomic local persistence."""
    folder = task_folder(tasks_root, task_id)
    preview = _script_data(folder).get("rick_scene_candidate_preview")
    if (not isinstance(preview, dict)
            or preview_sha256 != _preview_fingerprint(preview)):
        raise ValueError("A prévia de cenas foi alterada. Recarregue a revisão.")
    report = build_editorial_review(preview, downloaded_files, decisions)
    document = {
        "version": 1,
        "task_id": task_id,
        "preview_sha256": preview_sha256,
        "review": report,
        "note": "Revisão humana não implica autenticidade nem geração automática.",
    }
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, dir=folder,
            prefix=".rick-review-", suffix=".tmp",
        ) as f:
            tmp_path = Path(f.name)
            json.dump(document, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, folder / _REVIEW_FILE)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
    return report
