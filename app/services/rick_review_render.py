"""Offline export of a previously human-approved Rick scene review.

All assets are resolved from the original task's allowlisted local manifest.
No LLM/TTS/stock provider is called, no publication takes place, and the
original MP4, task state and human review are not modified.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.models.schema import VideoAspect, VideoConcatMode, VideoFitMode, VideoParams
from app.services import rick_scene_timeline, video, voice
from app.services.rick_editorial_workspace import (
    _script_data,
    load_review_workspace,
    task_folder,
)


def _safe_owned_file(folder: Path, basename: str, *, required: bool = True) -> Path | None:
    candidate = folder / basename
    if not candidate.is_file():
        if required:
            raise ValueError(f"Arquivo local necessário não encontrado: {basename}")
        return None
    if candidate.is_symlink() or candidate.resolve().parent != folder.resolve():
        raise ValueError(f"Arquivo local não autorizado: {basename}")
    if not 0 < candidate.stat().st_size <= 256 * 1024 * 1024:
        raise ValueError(f"Tamanho de arquivo inválido: {basename}")
    return candidate


def prepare_reviewed_export(
    tasks_root: str | Path,
    task_id: str,
    *,
    cache_dir: str | Path | None = None,
    without_subtitles: bool = False,
) -> dict[str, Any]:
    """Fail closed unless all scenes and available files are human-approved."""
    folder = task_folder(tasks_root, task_id)
    workspace = load_review_workspace(
        tasks_root, task_id, [], cache_dir=cache_dir,
    )
    review = workspace["saved_review"]
    if not isinstance(review, dict) or review.get("status") != "ready_human_reviewed":
        raise ValueError(
            "Revisão editorial incompleta. Aprove TODAS as cenas antes de exportar."
        )
    scenes = review.get("scenes")
    if (
        not isinstance(scenes, list) or not scenes
        or review.get("human_approved_count") != len(scenes)
        or any(not isinstance(scene, dict) or
               scene.get("editorial_review") != "approved_by_human"
               for scene in scenes)
    ):
        raise ValueError("Revisão não contém aprovação humana completa.")

    audio = _safe_owned_file(folder, "audio.mp3")
    try:
        measured = float(voice.get_audio_duration(str(audio)))
        planned = float(scenes[-1]["end_seconds"])
    except (TypeError, ValueError, KeyError, OSError, OverflowError) as exc:
        raise ValueError("Não foi possível medir o áudio original da tarefa.") from exc
    if (
        not math.isfinite(measured) or measured <= 0
        or not math.isfinite(planned) or planned <= 0
        or abs(measured - planned) > 0.25
    ):
        raise ValueError(
            "A duração do áudio difere do plano aprovado. Recrie a prévia antes de exportar."
        )

    manifest = _script_data(folder)
    raw_params = manifest.get("params")
    if not isinstance(raw_params, dict):
        raw_params = {}
    original_wants_subtitles = raw_params.get("subtitle_enabled") is True
    subtitle = _safe_owned_file(
        folder, "subtitle.srt", required=original_wants_subtitles and not without_subtitles
    ) if original_wants_subtitles and not without_subtitles else None
    # Reject absent original subtitles rather than silently losing captions.
    max_clip = raw_params.get("video_clip_duration", 4)
    if type(max_clip) is not int or not 1 <= max_clip <= 20:
        max_clip = 4

    allowed_paths = workspace["paths"]
    ordered_paths = list(allowed_paths.values())
    timeline = rick_scene_timeline.build_scene_render_preflight(
        review, ordered_paths, planned, max_clip_seconds=max_clip,
    )
    if timeline["status"] != "ready_metadata_only" or not timeline["segments"]:
        raise ValueError(
            "Montagem bloqueada: uma ou mais cenas não possuem clipe aprovado e disponível."
        )

    # Reuse only visual style, not credentials, remote paths, background music
    # providers, publication settings or user-supplied file paths.
    style_keys = (
        "font_name", "font_size", "stroke_width", "stroke_color",
        "text_fore_color", "text_background_color", "subtitle_position",
        "subtitle_display_mode", "subtitle_animation",
        "rounded_subtitle_background", "custom_position", "voice_volume",
        "video_fit_mode",
    )
    style = {key: raw_params[key] for key in style_keys if key in raw_params}
    params = VideoParams(
        video_subject=str(raw_params.get("video_subject") or "Vídeo Rick revisado")[:300],
        video_aspect=VideoAspect.portrait,
        video_concat_mode=VideoConcatMode.sequential,
        subtitle_enabled=subtitle is not None,
        bgm_type="",
        bgm_file="",
        bgm_volume=0.0,
        video_count=1,
        video_clip_duration=max_clip,
        video_clip_speed=1.0,
        **style,
    )
    # Preserve default framing if the saved property is absent.
    params.video_fit_mode = VideoFitMode(params.video_fit_mode)
    return {
        "task_dir": str(folder),
        "task_id": task_id,
        "audio": str(audio),
        "subtitle": str(subtitle) if subtitle else "",
        "paths": ordered_paths,
        "timeline": timeline,
        "params": params,
        "review_sha256": workspace["preview_sha256"],
        "recovered_preview": workspace["recovered_preview"],
        "scene_count": len(scenes),
        "duration": measured,
    }


def export_reviewed_video(
    tasks_root: str | Path,
    task_id: str,
    *,
    cache_dir: str | Path | None = None,
    without_subtitles: bool = False,
) -> dict[str, Any]:
    """Render ONLY to new task-owned files after the review passes preflight."""
    job = prepare_reviewed_export(
        tasks_root, task_id, cache_dir=cache_dir,
        without_subtitles=without_subtitles,
    )
    folder = Path(job["task_dir"])
    output_dir = folder / "rick_reviewed_exports"
    if output_dir.is_symlink():
        raise ValueError("Pasta de saída não autorizada.")
    output_dir.mkdir(exist_ok=True)
    if output_dir.resolve().parent != folder.resolve():
        raise ValueError("Pasta de saída fora da tarefa.")
    run_id = uuid4().hex[:12]
    combined = output_dir / f"rick-reviewed-{run_id}-combined.mp4"
    final = output_dir / f"rick-reviewed-{run_id}-final.mp4"
    summary = output_dir / f"rick-reviewed-{run_id}-report.json"

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
        threads=2,
        clip_speed=1.0,
        scene_timeline=job["timeline"],
        used_video_paths=used,
    )
    video.generate_video(
        video_path=str(combined),
        audio_path=job["audio"],
        subtitle_path=job["subtitle"],
        output_file=str(final),
        params=job["params"],
        bgm_file_override="",
    )
    if not final.is_file() or final.stat().st_size <= 0:
        raise RuntimeError("A montagem terminou sem gerar um MP4 válido.")
    report = {
        "version": 1,
        "status": "rendered_from_human_review",
        "task_id": task_id,
        "preview_sha256": job["review_sha256"],
        "scene_count": job["scene_count"],
        "subtitle_included": bool(job["subtitle"]),
        "background_music_reused": False,
        "alignment": "estimated",
        "human_review_source": "rick_editorial_review.json",
        "output_filename": final.name,
        "used_source_basenames": [Path(value).name for value in used],
        "warnings": [
            "Tempos de cenas estimados; revisão humana não certifica autenticidade ou direitos.",
            "Esta exportação não altera o vídeo original nem o estado da tarefa.",
        ],
    }
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".rick-export-",
            suffix=".tmp", dir=output_dir, delete=False,
        ) as file:
            temporary = Path(file.name)
            json.dump(report, file, ensure_ascii=False, indent=2)
        os.replace(temporary, summary)
        temporary = None
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return {"output": str(final), "report": str(summary), **report}
