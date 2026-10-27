"""Local-only, read-only-by-default workspace for human scene reviews.

This module discovers already-downloaded files from the task state/manifest,
stores an optional editorial decision artifact, and NEVER renders or publishes.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services.rick_editorial_review import build_editorial_review
from app.services.rick_scene_assignment import assign_scene_candidates
from app.services.rick_scene_plan import build_scene_plan

_TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".webm", ".avi"})
_REVIEW_FILE = "rick_editorial_review.json"
_MAX_SCRIPT_BYTES = 4 * 1024 * 1024
_MAX_LEGACY_AUDIO_BYTES = 256 * 1024 * 1024


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



def _measure_legacy_local_audio(folder: Path) -> float | None:
    """Measure only the task's standard audio.mp3, without external requests.

    Historical task state can be absent after restarting/migrating machines.
    Never accept a manifest-provided path or infer narration duration from
    a final edited video with music/fades/trailing silence.
    """
    audio = folder / "audio.mp3"
    try:
        if (not audio.is_file() or audio.is_symlink()
                or audio.resolve().parent != folder
                or not 0 < audio.stat().st_size <= _MAX_LEGACY_AUDIO_BYTES):
            return None
        # Import only for legacy recovery to avoid decoding on every UI rerun.
        from app.services import voice

        measured = float(voice.get_audio_duration(str(audio)))
    except (OSError, TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(measured) or not 0 < measured <= 1800:
        return None
    return round(measured, 3)


def _reconstruct_legacy_preview(
    manifest: Mapping[str, Any],
    safe_paths: Mapping[str, str],
    audio_duration: Any,
    *,
    folder: Path | None = None,
) -> dict[str, Any]:
    """Offline estimate from historical task records; never invents assets.

    An old task is eligible only when its original script, downloaded stock
    provenance, actual local files, and measured audio time still exist.
    Reconstructed suggestions are NOT claims of visual accuracy.
    """
    script = manifest.get("script")
    if not isinstance(script, str) or not script.strip():
        raise ValueError("Tarefa sem prévia por cena e sem texto do roteiro preservado.")
    records = manifest.get("material_sources")
    if not isinstance(records, list) or not records or not safe_paths:
        raise ValueError(
            "Tarefa antiga sem materiais de banco registrados e disponíveis. "
            "Não é possível reconstruir os candidatos sem esses arquivos."
        )
    if audio_duration is None:
        quality = manifest.get("rick_quality")
        if isinstance(quality, Mapping):
            diagnostic = quality.get("audio_duration")
            if isinstance(diagnostic, Mapping):
                audio_duration = diagnostic.get("seconds")
    if audio_duration is None and folder is not None:
        audio_duration = _measure_legacy_local_audio(folder)
    if isinstance(audio_duration, bool):
        audio_duration = None
    try:
        seconds = float(audio_duration)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            "Tarefa antiga sem duração medida do áudio no estado/diagnóstico. "
            "Não é seguro reconstruir intervalos de cenas."
        ) from exc
    if not math.isfinite(seconds) or seconds <= 0 or seconds > 1800:
        raise ValueError("Duração do áudio inválida para reconstrução offline.")

    params = manifest.get("params")
    if not isinstance(params, Mapping):
        params = {}
    source = params.get("video_source")
    if source not in ("pixabay", "pexels", "coverr"):
        raise ValueError("Recuperação disponível apenas para vídeos de banco.")
    clip = params.get("video_clip_duration", 4)
    if isinstance(clip, bool):
        raise ValueError("Duração de clipe histórica inválida.")
    try:
        clip_seconds = float(clip)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Duração de clipe histórica inválida.") from exc
    if not math.isfinite(clip_seconds) or not 0 < clip_seconds <= 60:
        raise ValueError("Duração de clipe histórica inválida.")

    raw_terms = manifest.get("search_terms", "")
    if isinstance(raw_terms, str):
        terms = re.split(r"[,，]", raw_terms)
    elif isinstance(raw_terms, list) and all(isinstance(t, str) for t in raw_terms):
        terms = raw_terms
    else:
        terms = []
    plan = build_scene_plan(
        script, terms, seconds, target_clip_seconds=clip_seconds
    )
    preview = assign_scene_candidates(
        plan, records, available_files=list(safe_paths.values())
    )
    preview["recovered_from_historical_records"] = True
    preview["warnings"].append({
        "code": "historical_offline_estimate",
        "message": (
            "Estimativa reconstruída de registros antigos. Trechos, tempos e "
            "correspondências precisam de revisão humana."
        ),
    })
    return preview


def available_material_paths(
    material_sources: Sequence[Mapping[str, Any]],
    state_materials: Sequence[str],
    *,
    cache_dir: str | Path | None = None,
) -> dict[str, str]:
    """Resolve recorded videos from existing task state or a trusted cache.

    Do not enumerate the whole cache as selectable content. A cache candidate
    must match an EXACT safe basename already registered in material_sources.
    The manifest never supplies a filesystem path or a cache directory.
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
    ambiguous = {name for name, count in counts.items() if count != 1}
    result = {
        p.name: str(p.resolve())
        for p in safe_paths
        if p.name not in ambiguous
    }
    # Older tasks may store valid provenance in script.json but lose their
    # transient state.materials after a restart. Stock assets live in the
    # app-controlled cache, not in the task's own folder.
    if cache_dir is not None:
        root = Path(cache_dir)
        try:
            if not root.is_dir() or root.is_symlink():
                return result
            resolved_root = root.resolve()
            for name in allowed_names - result.keys() - ambiguous:
                candidate = root / name
                if (candidate.is_file() and not candidate.is_symlink()
                        and candidate.stat().st_size > 0
                        and candidate.resolve().parent == resolved_root):
                    result[name] = str(candidate.resolve())
        except OSError:
            # Cache access is optional; never block an existing valid state.
            pass
    return result


def load_review_workspace(
    tasks_root: str | Path,
    task_id: str,
    state_materials: Sequence[str],
    *,
    audio_duration: Any = None,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    folder = task_folder(tasks_root, task_id)
    manifest = _script_data(folder)
    paths = available_material_paths(
        manifest.get("material_sources", []), state_materials,
        cache_dir=cache_dir,
    )
    preview = manifest.get("rick_scene_candidate_preview")
    recovered = not isinstance(preview, dict)
    if recovered:
        preview = _reconstruct_legacy_preview(
            manifest, paths, audio_duration, folder=folder
        )
    scenes = preview.get("scenes")
    if (
        not isinstance(scenes, list)
        or not 1 <= len(scenes) <= 60
        or any(not isinstance(scene, dict) for scene in scenes)
    ):
        raise ValueError("Prévia de cenas inválida.")
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
        if isinstance(name, str) and name in paths and name not in source_metadata:
            source_metadata[name] = {
                "provider": str(record.get("provider") or "não informado")[:80],
                "source_page": str(record.get("source_page") or "")[:400],
            }
    return {
        "task_id": task_id,
        "task_dir": str(folder),
        "source_metadata": source_metadata,
        "preview": preview,
        "recovered_preview": recovered,
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
    *,
    audio_duration: Any = None,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Revalidate historical/live sources before atomic local persistence."""
    folder = task_folder(tasks_root, task_id)
    manifest = _script_data(folder)
    preview = manifest.get("rick_scene_candidate_preview")
    if not isinstance(preview, dict):
        safe_paths = available_material_paths(
            manifest.get("material_sources", []), downloaded_files,
            cache_dir=cache_dir,
        )
        preview = _reconstruct_legacy_preview(
            manifest, safe_paths, audio_duration, folder=folder
        )
    if preview_sha256 != _preview_fingerprint(preview):
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
