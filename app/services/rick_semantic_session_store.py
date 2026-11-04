"""Local persistence for opt-in Gemini editorial assessments, not approvals.

Only analysis evidence and task-owned filenames are saved: no API keys, raw
images, downloaded bytes, publishing configuration or user credentials.
A batch is bound to the current task preview, pre-curation primary clips
and Gemini model. Stale/edited files and corrupt records are ignored.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.services.rick_editorial_workspace import task_folder
from app.services.rick_semantic_remediation import proposal_fingerprint

_VERSION = 1
_MAX_BYTES = 512 * 1024
_ASSESSMENT_KEYS = (
    "scene_number", "file", "verdict", "visible_evidence", "reason",
    "status", "visual_relation", "recommended_action", "failure_stage",
    "requires_strict_review",
)
_COMPARISON_KEYS = (
    *_ASSESSMENT_KEYS, "original_file", "metadata_score",
    "candidate_order", "source_page", "license_metadata",
    "selected_as_primary", "rights_verified",
)
_RANKING_KEYS = (
    "scene_number", "candidates_examined", "direct_candidates",
    "suggested_file", "status", "basis", "human_approved",
    "license_verified", "auto_selection_permitted",
    "publishing_permitted",
)


def _file(tasks_root: str | Path, task_id: str, first_scene: int) -> Path:
    if type(first_scene) is not int or first_scene not in range(1, 61, 6):
        raise ValueError("Lote de cenas inválido.")
    return task_folder(tasks_root, task_id) / (
        f"rick_semantic_batch_{first_scene:02d}.json"
    )


def _identity(workspace: Mapping, proposals: Mapping, model: str, first_scene: int) -> dict:
    preview_hash = workspace.get("preview_sha256")
    if (
        not isinstance(preview_hash, str) or len(preview_hash) != 64
        or not isinstance(model, str) or not 0 < len(model.strip()) <= 100
    ):
        raise ValueError("Prévia ou modelo Gemini inválidos.")
    return {
        "version": _VERSION,
        "first_scene": first_scene,
        "model": model.strip(),
        "preview_sha256": preview_hash,
        "precuration_sha256": proposal_fingerprint(proposals),
    }


def _clip(value: object) -> object:
    """Discard excessive Gemini text without introducing serialization secrets."""
    if isinstance(value, str):
        return value[:2000]
    return value


def _row(record: Mapping, keys: tuple[str, ...]) -> dict:
    return {key: _clip(record[key]) for key in keys if key in record}


def _clean_assessment(assessment: Mapping) -> dict:
    return {
        key: _clip(assessment[key])
        for key in (
            "version", "provider", "model", "assessed", "attempted",
            "api_requests", "semantic_content_verified",
            "visual_identity_verified", "rights_verified",
            "human_approved", "publishing_permitted", "warning",
        ) if key in assessment
    } | {
        "results": [
            _row(row, _ASSESSMENT_KEYS)
            for row in assessment.get("results", [])
            if isinstance(row, Mapping)
        ],
    }


def _clean_recovery(recovery: Mapping) -> dict:
    discovery = recovery.get("discovery")
    return {
        key: _clip(recovery[key])
        for key in (
            "version", "model", "source_preview_sha256",
            "source_precuration_sha256", "max_candidates_per_scene",
            "api_requests", "ai_assessed", "human_approved",
            "publishing_permitted", "original_proposals_unchanged",
            "note",
        ) if key in recovery
    } | {
        "targets": list(recovery.get("targets", [])),
        "compared": [
            _row(row, _COMPARISON_KEYS)
            for row in recovery.get("compared", [])
            if isinstance(row, Mapping)
        ],
        "ranking": [
            _row(row, _RANKING_KEYS)
            for row in recovery.get("ranking", [])
            if isinstance(row, Mapping)
        ],
        "unresolved": [
            _row(row, ("scene_number", "status"))
            for row in recovery.get("unresolved", [])
            if isinstance(row, Mapping)
        ],
        "discovery": {
            "imported_count": discovery.get("imported_count", 0)
        } if isinstance(discovery, Mapping) else {},
    }


def _valid_assessment(
    value: object, *, proposals: Mapping, workspace: Mapping,
    model: str, first_scene: int,
) -> bool:
    if (
        not isinstance(value, Mapping)
        or value.get("version") != 2
        or value.get("model") != model
        or not isinstance(value.get("results"), list)
        or not 1 <= len(value["results"]) <= 6
        or not isinstance(proposals.get("scenes"), list)
    ):
        return False
    base = {
        row.get("scene_number"): row.get("primary")
        for row in proposals["scenes"]
        if isinstance(row, Mapping)
    }
    paths = workspace.get("paths")
    if not isinstance(paths, Mapping):
        return False
    allowed_statuses = {
        "ai_assessment_for_human_review", "provider_or_response_failure",
        "frames_unavailable", "invalid_local_media", "not_evaluated",
    }
    seen: set[int] = set()
    for row in value["results"]:
        if not isinstance(row, Mapping):
            return False
        num = row.get("scene_number")
        if (
            type(num) is not int or not first_scene <= num < first_scene + 6
            or num in seen or base.get(num) != row.get("file")
            or not isinstance(row.get("file"), str)
            or row["file"] not in paths
            or not isinstance(row.get("status"), str)
            or row["status"] not in allowed_statuses
            or not isinstance(row.get("verdict"), str)
            or not isinstance(row.get("visual_relation"), str)
            or not isinstance(row.get("visible_evidence"), str)
            or not isinstance(row.get("reason"), str)
        ):
            return False
        seen.add(num)
    return True


def _valid_recovery(
    recovery: object, *, assessment: Mapping, workspace: Mapping,
    proposals: Mapping, model: str, first_scene: int,
) -> bool:
    if (
        not isinstance(recovery, Mapping)
        or recovery.get("version") != 1
        or recovery.get("model") != model
        or recovery.get("source_preview_sha256")
        != workspace.get("preview_sha256")
        or recovery.get("source_precuration_sha256")
        != proposal_fingerprint(proposals)
        or not isinstance(recovery.get("targets"), list)
        or not 1 <= len(recovery["targets"]) <= 3
        or not isinstance(recovery.get("compared"), list)
        or not isinstance(recovery.get("ranking"), list)
        or len(recovery["compared"]) > 6
        or len(recovery["ranking"]) > 3
    ):
        return False
    targets = recovery["targets"]
    originals = {
        row["scene_number"]: row["primary"]
        for row in proposals["scenes"]
        if isinstance(row, Mapping) and type(row.get("scene_number")) is int
    }
    assessment_rows = {
        row["scene_number"]: row
        for row in assessment["results"]
    }
    paths = workspace.get("paths")
    if not isinstance(paths, Mapping):
        return False
    if (
        any(type(n) is not int or n not in assessment_rows for n in targets)
        or len(set(targets)) != len(targets)
    ):
        return False
    saved = workspace.get("saved_review") or {}
    human_scenes = saved.get("scenes", []) if isinstance(saved, Mapping) else []
    for number in targets:
        original = originals.get(number)
        row = assessment_rows[number]
        if (
            row.get("status") != "ai_assessment_for_human_review"
            or (row.get("verdict") == "plausible"
                and row.get("visual_relation") == "direct")
            or original is None or original != row.get("file")
            or (
                isinstance(human_scenes, list)
                and len(human_scenes) >= number
                and isinstance(human_scenes[number - 1], Mapping)
                and human_scenes[number - 1].get("editorial_review")
                == "approved_by_human"
            )
        ):
            return False
    for row in recovery["compared"]:
        if not isinstance(row, Mapping):
            return False
        number = row.get("scene_number")
        if (
            type(number) is not int or number not in targets
            or row.get("original_file") != originals[number]
            or not isinstance(row.get("file"), str)
            or row["file"] not in paths
            or not isinstance(row.get("verdict"), str)
            or not isinstance(row.get("visual_relation"), str)
            or not isinstance(row.get("visible_evidence"), str)
        ):
            return False
    for row in recovery["ranking"]:
        if not isinstance(row, Mapping):
            return False
        number = row.get("scene_number")
        suggested = row.get("suggested_file")
        if (
            type(number) is not int or number not in targets
            or (
                suggested is not None
                and (not isinstance(suggested, str) or suggested not in paths)
            )
            or not isinstance(row.get("status"), str)
            or type(row.get("candidates_examined")) is not int
            or type(row.get("direct_candidates")) is not int
        ):
            return False
    return True


def load_semantic_batch(
    tasks_root: str | Path,
    task_id: str,
    *,
    first_scene: int,
    workspace: Mapping,
    proposals: Mapping,
    model: str,
) -> dict[str, Any]:
    """Read valid local evidence without any provider calls or filesystem writes."""
    empty: dict[str, Any] = {"assessment": None, "history": {}}
    path = _file(tasks_root, task_id, first_scene)
    identity = _identity(workspace, proposals, model, first_scene)
    try:
        if (
            path.is_symlink() or not path.is_file()
            or not 0 < path.stat().st_size <= _MAX_BYTES
        ):
            return empty
        contents = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
        return empty
    if (
        not isinstance(contents, dict)
        or any(contents.get(key) != value for key, value in identity.items())
        or not _valid_assessment(
            contents.get("assessment"),
            proposals=proposals, workspace=workspace,
            model=model, first_scene=first_scene,
        )
    ):
        return empty
    assessment = contents["assessment"]
    raw_history = contents.get("history")
    history: dict[str, dict] = {}
    used: set[int] = set()
    if isinstance(raw_history, dict):
        for group_key, recovery in raw_history.items():
            if (
                not isinstance(group_key, str)
                or not _valid_recovery(
                    recovery, assessment=assessment, workspace=workspace,
                    proposals=proposals, model=model, first_scene=first_scene,
                )
                or group_key != ",".join(map(str, recovery["targets"]))
                or used.intersection(recovery["targets"])
            ):
                continue
            used.update(recovery["targets"])
            history[group_key] = recovery
    return {"assessment": assessment, "history": history}


def _atomic_write(path: Path, data: dict) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("Arquivo de análise local não autorizado.")
    encoded = json.dumps(
        data, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > _MAX_BYTES:
        raise ValueError("Histórico semântico excede o limite de armazenamento.")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=".rick-semantic-",
            suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def record_semantic_assessment(
    tasks_root: str | Path,
    task_id: str,
    *,
    first_scene: int,
    workspace: Mapping,
    proposals: Mapping,
    model: str,
    assessment: Mapping,
) -> None:
    """Replace only this batch: a new baseline invalidates old comparisons."""
    if not isinstance(assessment, Mapping):
        raise ValueError("Avaliação Gemini inválida.")
    clean = _clean_assessment(assessment)
    if not _valid_assessment(
        clean, proposals=proposals, workspace=workspace,
        model=model, first_scene=first_scene,
    ):
        raise ValueError("Avaliação Gemini não corresponde à cena atual.")
    path = _file(tasks_root, task_id, first_scene)
    _atomic_write(path, {
        **_identity(workspace, proposals, model, first_scene),
        "assessment": clean,
        "history": {},
    })


def record_semantic_recovery(
    tasks_root: str | Path,
    task_id: str,
    *,
    first_scene: int,
    workspace: Mapping,
    proposals: Mapping,
    model: str,
    recovery: Mapping,
) -> dict[str, Any]:
    """Append exactly one already-assessed group; reject duplicate/foreign work."""
    stored = load_semantic_batch(
        tasks_root, task_id, first_scene=first_scene, workspace=workspace,
        proposals=proposals, model=model,
    )
    if not isinstance(stored["assessment"], Mapping) or not isinstance(recovery, Mapping):
        raise ValueError("Salve primeiro a avaliação Gemini do lote atual.")
    clean = _clean_recovery(recovery)
    if not _valid_recovery(
        clean, assessment=stored["assessment"], workspace=workspace,
        proposals=proposals, model=model, first_scene=first_scene,
    ):
        raise ValueError("Recuperação incompatível com as cenas atuais.")
    key = ",".join(map(str, clean["targets"]))
    history = dict(stored["history"])
    if key in history or any(
        set(row["targets"]).intersection(clean["targets"])
        for row in history.values()
    ):
        raise ValueError("Estas cenas já tiveram a recuperação registrada.")
    history[key] = clean
    path = _file(tasks_root, task_id, first_scene)
    _atomic_write(path, {
        **_identity(workspace, proposals, model, first_scene),
        "assessment": stored["assessment"],
        "history": history,
    })
    return {"assessment": stored["assessment"], "history": history}
