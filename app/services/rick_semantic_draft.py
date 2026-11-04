"""Explicit, offline draft MP4 using conservative Gemini scene suggestions.

This IS NOT an editorial-approval export. Unassessed scenes retain the
metadata-based original proposal and are individually labeled as such in
the report. No provider network calls, LLM calls, publication or changes
to the source task, review record and original video are permitted.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import uuid4

from app.models.schema import VideoAspect, VideoConcatMode
from app.services import rick_scene_timeline, video, voice
from app.services.rick_auto_movie import _render_params
from app.services.rick_editorial_workspace import (
    _script_data, load_review_workspace, task_folder,
)
from app.services.rick_review_render import _safe_owned_file
from app.services.rick_semantic_remediation import proposal_fingerprint


def build_semantic_draft_assignments(
    workspace: Mapping,
    proposals: Mapping,
    recovery_history: Mapping,
) -> dict:
    """Prepare an inspectable plan; do not claim fallback material is suitable.

    A recommendation can only replace a metadata fallback if the matching
    assessment actually observed a plausible DIRECT relation, with evidence.
    All inputs must refer to this exact local preview and proposal fingerprint.
    """
    preview = workspace.get("preview")
    paths = workspace.get("paths")
    if (
        not isinstance(preview, Mapping)
        or not isinstance(paths, Mapping)
        or not isinstance(preview.get("scenes"), list)
        or not isinstance(proposals, Mapping)
        or not isinstance(proposals.get("scenes"), list)
        or len(proposals["scenes"]) != len(preview["scenes"])
        or not 1 <= len(preview["scenes"]) <= 60
        or not isinstance(recovery_history, Mapping)
        or not recovery_history
    ):
        raise ValueError("Prévia, materiais ou comparações incompatíveis.")
    proposal_hash = proposal_fingerprint(proposals)
    preview_hash = workspace.get("preview_sha256")
    if not isinstance(preview_hash, str):
        raise ValueError("Identificador da prévia ausente.")
    candidates = {}
    rows = []
    for index, (scene, proposal) in enumerate(
        zip(preview["scenes"], proposals["scenes"]), 1
    ):
        if (
            not isinstance(scene, Mapping)
            or not isinstance(proposal, Mapping)
            or proposal.get("scene_number") != index
            or proposal.get("text") != scene.get("text")
        ):
            raise ValueError("A pré-curadoria foi modificada: atualize a análise.")
        name = proposal.get("primary")
        if (
            not isinstance(name, str)
            or name not in paths
            or not isinstance(paths[name], str)
        ):
            raise ValueError(
                f"Cena {index} sem mídia local atual disponível; montagem bloqueada."
            )
        row = {
            "scene_number": index,
            "text": str(scene.get("text") or "")[:250],
            "start_seconds": scene.get("start_seconds"),
            "end_seconds": scene.get("end_seconds"),
            "original_file": name,
            "assigned_material_file": name,
            "match_status": "term_match_unverified",
            "selection_basis": "original_metadata_unverified",
            "visual_relation": "not_assessed_as_direct",
            "human_approved": False,
            "rights_verified": False,
            "source_page": "",
        }
        rows.append(row)

    for key, recovery in recovery_history.items():
        if (
            not isinstance(key, str) or not isinstance(recovery, Mapping)
            or recovery.get("version") != 1
            or recovery.get("source_preview_sha256") != preview_hash
            or recovery.get("source_precuration_sha256") != proposal_hash
            or not isinstance(recovery.get("model"), str)
            or not recovery["model"]
        ):
            raise ValueError(
                "Comparações antigas ou de outra prévia; reavalie o lote."
            )
        targets = recovery.get("targets")
        comparisons = recovery.get("compared")
        rankings = recovery.get("ranking")
        if (
            not isinstance(targets, list)
            or not 1 <= len(targets) <= 3
            or any(type(n) is not int or not 1 <= n <= len(rows) for n in targets)
            or len(set(targets)) != len(targets)
            or not isinstance(comparisons, list)
            or not isinstance(rankings, list)
        ):
            raise ValueError("Grupo de comparações inválido.")
        if key != ",".join(str(n) for n in targets):
            raise ValueError("Identificação de grupo não corresponde às cenas.")
        for rank in rankings:
            if not isinstance(rank, Mapping):
                raise ValueError("Ranking de mídia inválido.")
            number = rank.get("scene_number")
            if type(number) is not int or number not in targets:
                raise ValueError("Ranking fora do grupo de cenas.")
            name = rank.get("suggested_file")
            if name is None:
                continue  # No direct evidence: keep metadata fallback, explicitly.
            if (
                not isinstance(name, str)
                or name not in paths
                or name == rows[number - 1]["original_file"]
                or rank.get("status") != "candidato_para_revisao_humana"
                or rank.get("auto_selection_permitted") is not False
                or rank.get("publishing_permitted") is not False
            ):
                raise ValueError("Sugestão de mídia inválida ou desatualizada.")
            matched = [
                result for result in comparisons
                if isinstance(result, Mapping)
                and result.get("scene_number") == number
                and result.get("file") == name
                and result.get("original_file") == rows[number - 1]["original_file"]
                and result.get("status") == "ai_assessment_for_human_review"
                and result.get("verdict") == "plausible"
                and result.get("visual_relation") == "direct"
                and isinstance(result.get("visible_evidence"), str)
                and result["visible_evidence"].strip()
            ]
            if len(matched) != 1:
                raise ValueError(
                    "Recomendação sem evidência direta correspondente; bloqueada."
                )
            if number in candidates:
                raise ValueError("Cena recebeu duas recomendações incompatíveis.")
            candidates[number] = matched[0]

    for number, match in candidates.items():
        row = rows[number - 1]
        row["assigned_material_file"] = match["file"]
        row["selection_basis"] = "gemini_direct_candidate_not_human_approved"
        row["visual_relation"] = "direct_ai_assessed_not_verified"
        row["source_page"] = str(match.get("source_page") or "")[:400]
    if not candidates:
        raise ValueError(
            "Nenhuma alternativa com relação visual direta plausível foi "
            "encontrada; prévia semântica não seria diferente da original."
        )

    ordered_names = list(dict.fromkeys(
        row["assigned_material_file"] for row in rows
    ))
    # Resolve filenames only through the task's allowlisted workspace.
    return {
        "scenes": rows,
        "paths": [paths[name] for name in ordered_names],
        "recommended_count": len(candidates),
        "fallback_count": len(rows) - len(candidates),
        "recommended_scenes": sorted(candidates),
        "fallback_scenes": [
            r["scene_number"] for r in rows
            if r["selection_basis"] == "original_metadata_unverified"
        ],
        "preview_sha256": preview_hash,
        "precuration_sha256": proposal_hash,
        "status": "machine_draft_not_human_reviewed",
        "publishing_permitted": False,
        "human_approved": False,
    }


def prepare_semantic_draft(
    tasks_root: str | Path,
    task_id: str,
    *,
    state_materials: list[str],
    cache_dir: str | Path,
    original_proposals: Mapping,
    recovery_history: Mapping,
    without_subtitles: bool = False,
) -> dict:
    """Fail closed before doing any work when inputs are stale/unavailable."""
    if (
        not isinstance(state_materials, list)
        or not isinstance(cache_dir, (str, Path))
        or type(without_subtitles) is not bool
    ):
        raise ValueError("Configuração de prévia semântica inválida.")
    folder = task_folder(tasks_root, task_id)
    ws = load_review_workspace(
        tasks_root, task_id, state_materials, cache_dir=cache_dir,
    )
    assignment = build_semantic_draft_assignments(
        ws, original_proposals, recovery_history,
    )
    audio = _safe_owned_file(folder, "audio.mp3")
    try:
        measured = float(voice.get_audio_duration(str(audio)))
        planned = float(assignment["scenes"][-1]["end_seconds"])
    except (TypeError, ValueError, KeyError, OSError, OverflowError) as exc:
        raise ValueError("Não foi possível medir a narração local.") from exc
    if (
        not math.isfinite(measured) or not math.isfinite(planned)
        or measured <= 0 or planned <= 0 or abs(measured - planned) > 0.25
    ):
        raise ValueError(
            "A duração do áudio difere dos intervalos da prévia; bloqueado."
        )
    manifest = _script_data(folder)
    raw = manifest.get("params")
    if not isinstance(raw, dict):
        raw = {}
    max_clip = raw.get("video_clip_duration", 4)
    if type(max_clip) is not int or not 1 <= max_clip <= 20:
        max_clip = 4
    include_subtitles = (
        raw.get("subtitle_enabled") is True and not without_subtitles
    )
    subtitle = (
        _safe_owned_file(folder, "subtitle.srt", required=True)
        if include_subtitles else None
    )
    preview = {
        "version": 1,
        "status": "machine_draft_not_human_reviewed",
        "scene_count": len(assignment["scenes"]),
        "alignment": "estimated",
        "scenes": [
            {
                "scene_number": row["scene_number"],
                "start_seconds": row["start_seconds"],
                "end_seconds": row["end_seconds"],
                "assigned_material_file": row["assigned_material_file"],
                "match_status": "term_match_unverified",
            }
            for row in assignment["scenes"]
        ],
    }
    timeline = rick_scene_timeline.build_scene_render_preflight(
        preview, assignment["paths"], planned, max_clip_seconds=max_clip,
    )
    if timeline["status"] != "ready_metadata_only" or not timeline["segments"]:
        raise ValueError(
            "A montagem de teste não passou na validação dos intervalos."
        )
    params = _render_params(
        manifest, include_subtitles=subtitle is not None, clip_seconds=max_clip,
    )
    return {
        "task_dir": str(folder),
        "task_id": task_id,
        "audio": str(audio),
        "subtitle": str(subtitle) if subtitle else "",
        "params": params,
        "timeline": timeline,
        **assignment,
    }


def export_semantic_draft(
    tasks_root: str | Path,
    task_id: str,
    *,
    state_materials: list[str],
    cache_dir: str | Path,
    original_proposals: Mapping,
    recovery_history: Mapping,
    without_subtitles: bool = False,
) -> dict:
    """Produce a distinct MP4 draft from local assets, with clear provenance."""
    job = prepare_semantic_draft(
        tasks_root, task_id, state_materials=state_materials,
        cache_dir=cache_dir, original_proposals=original_proposals,
        recovery_history=recovery_history, without_subtitles=without_subtitles,
    )
    folder = Path(job["task_dir"])
    directory = folder / "rick_semantic_drafts"
    if directory.is_symlink():
        raise ValueError("Pasta de rascunhos não autorizada.")
    directory.mkdir(exist_ok=True)
    if directory.resolve().parent != folder.resolve():
        raise ValueError("Pasta de rascunhos fora da tarefa.")
    run_id = uuid4().hex[:12]
    combined = directory / f"rick-draft-{run_id}-combined.mp4"
    final = directory / f"rick-draft-{run_id}-final.mp4"
    report_path = directory / f"rick-draft-{run_id}-report.json"
    used: list[str] = []
    video.combine_videos(
        combined_video_path=str(combined),
        video_paths=job["paths"],
        audio_file=job["audio"],
        video_aspect=VideoAspect.portrait,
        video_concat_mode=VideoConcatMode.sequential,
        video_transition_mode=None,
        max_clip_duration=job["params"].video_clip_duration,
        video_fit_mode=job["params"].video_fit_mode,
        clip_speed=1.0,
        threads=2,
        scene_timeline=job["timeline"],
        used_video_paths=used,
    )
    video.generate_video(
        video_path=str(combined), audio_path=job["audio"],
        subtitle_path=job["subtitle"], output_file=str(final),
        params=job["params"], bgm_file_override="",
    )
    if not final.is_file() or final.stat().st_size <= 0:
        raise RuntimeError("Prévia semântica não gerou um MP4 válido.")
    report = {
        "version": 1,
        "status": "draft_machine_suggested_not_human_approved",
        "task_id": task_id,
        "output_filename": final.name,
        "preview_sha256": job["preview_sha256"],
        "precuration_sha256": job["precuration_sha256"],
        "scene_count": len(job["scenes"]),
        "recommended_count": job["recommended_count"],
        "fallback_count": job["fallback_count"],
        "recommended_scenes": job["recommended_scenes"],
        "fallback_scenes": job["fallback_scenes"],
        "scene_assignments": job["scenes"],
        "used_source_basenames": [Path(p).name for p in used],
        "subtitle_included": bool(job["subtitle"]),
        "background_music_reused": False,
        "alignment": "estimated",
        "human_approved": False,
        "rights_legally_verified": False,
        "visual_identity_verified": False,
        "publishing_permitted": False,
        "warnings": [
            "RASCUNHO: sugestões Gemini não são aprovação nem validação histórica.",
            "Cenas restantes usam a mídia original de metadados NÃO verificada visualmente.",
            "Fontes e licenças não foram homologadas. Não publicar diretamente.",
            "A sincronização entre cenas e a narração é estimada.",
            "MP4 original, decisões humanas e estado da tarefa não foram alterados.",
        ],
    }
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=directory, mode="w", encoding="utf-8", delete=False,
            prefix=".rick-draft-", suffix=".tmp",
        ) as stream:
            tmp = Path(stream.name)
            json.dump(report, stream, ensure_ascii=False, indent=2)
        os.replace(tmp, report_path)
        tmp = None
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return {"output": str(final), "report": str(report_path), **report}
