"""One-click, opt-in Rick MP4 from machine-screened Commons stills.

This is explicitly *not* the human editorial approval path. It produces a new
local file and evidence report, never modifies the original MP4, never marks a
human review as approved, and never publishes media. Filename relevance and
machine-readable Commons licenses do NOT certify identity or legal status.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from app.models.schema import VideoAspect, VideoConcatMode, VideoFitMode, VideoParams
from app.services import rick_scene_timeline, video, voice
from app.services.rick_auto_commons import download_commons_still, find_commons_stills
from app.services.rick_editorial_assets import import_editorial_material
from app.services.rick_editorial_workspace import (
    _script_data, load_review_workspace, task_folder,
)
from app.services.rick_review_render import _safe_owned_file
from app.services.rick_visual_curation import person_anchor


def _render_params(manifest: dict, *, include_subtitles: bool, clip_seconds: int) -> VideoParams:
    raw = manifest.get("params")
    if not isinstance(raw, dict):
        raw = {}
    keep = (
        "font_name", "font_size", "stroke_width", "stroke_color",
        "text_fore_color", "text_background_color", "subtitle_position",
        "subtitle_display_mode", "subtitle_animation",
        "rounded_subtitle_background", "custom_position", "voice_volume",
        "video_fit_mode",
    )
    style = {name: raw[name] for name in keep if name in raw}
    params = VideoParams(
        video_subject=str(raw.get("video_subject") or "Vídeo Rick automático")[:300],
        video_aspect=VideoAspect.portrait,
        video_concat_mode=VideoConcatMode.sequential,
        subtitle_enabled=include_subtitles,
        bgm_type="", bgm_file="", bgm_volume=0.0,
        video_count=1, video_clip_duration=clip_seconds, video_clip_speed=1.0,
        **style,
    )
    params.video_fit_mode = VideoFitMode(params.video_fit_mode)
    return params


def export_auto_commons_video(
    tasks_root: str | Path,
    task_id: str,
    *,
    cache_dir: str | Path,
    state_materials: list[str] | None = None,
    subject: str,
    max_images: int = 5,
    without_subtitles: bool = False,
) -> dict:
    """Automatically source, place and render images for a historical-person task.

    Limited first release: a clearly named historic subject is required.
    Do not fall back to unrelated stock footage. Fail closed when no Commons
    photo with restricted license metadata is found.
    """
    if not isinstance(cache_dir, (str, Path)):
        raise ValueError("Cache confiável obrigatório.")
    if not isinstance(subject, str) or len(subject) > 500:
        raise ValueError("Assunto inválido.")
    if not 1 <= max_images <= 8:
        raise ValueError("Quantidade de imagens inválida.")
    historical_person = person_anchor(subject)
    if not historical_person:
        raise ValueError(
            "Não identifiquei uma pessoa histórica no assunto. "
            "A busca automática documental ainda exige esse contexto."
        )
    folder = task_folder(tasks_root, task_id)
    manifest = _script_data(folder)
    ws = load_review_workspace(
        tasks_root, task_id, state_materials or [], cache_dir=cache_dir,
    )
    scenes = ws["preview"]["scenes"]
    if not 1 <= len(scenes) <= 60:
        raise ValueError("Plano de cenas inválido.")
    audio = _safe_owned_file(folder, "audio.mp3")
    measured = float(voice.get_audio_duration(str(audio)))
    planned = float(scenes[-1]["end_seconds"])
    if (not math.isfinite(measured) or not math.isfinite(planned)
            or measured <= 0 or abs(measured - planned) > 0.25):
        raise ValueError("Áudio original e tempos das cenas não coincidem.")

    raw = manifest.get("params") if isinstance(manifest.get("params"), dict) else {}
    wants_subtitles = raw.get("subtitle_enabled") is True and not without_subtitles
    subtitle = _safe_owned_file(
        folder, "subtitle.srt", required=wants_subtitles
    ) if wants_subtitles else None
    max_clip = raw.get("video_clip_duration", 4)
    if type(max_clip) is not int or not 1 <= max_clip <= 20:
        max_clip = 4

    # A new project render must not inherit the old task's unverified media
    # or a human approval from an unrelated review session.
    images = find_commons_stills(historical_person, max_results=max_images)
    if not images:
        raise ValueError(
            "O Commons não retornou imagens vinculadas ao assunto com "
            "metadados CC0/domínio público suficientes. Montagem bloqueada."
        )
    imported: list[dict] = []
    for i, candidate in enumerate(images, 1):
        note = (
            f"Commons: {candidate['source_page']} | "
            f"licença informada: {candidate['license']}"
        )
        # No truncation of citations: an incomplete URL would be misleading.
        if len(note) > 350:
            continue
        try:
            name, image_bytes = download_commons_still(candidate)
            filename = import_editorial_material(
                tasks_root, task_id, name, image_bytes,
                scene_number=min(i, len(scenes)), source_note=note,
            )
        except (ValueError, OSError, RuntimeError):
            # Individual unavailable thumbnails may be skipped; never use
            # an unrelated local stock video as a substitute.
            continue
        imported.append({**candidate, "local_file": filename})
    if not imported:
        raise ValueError(
            "Nenhuma imagem elegível pôde ser obtida e convertida. "
            "Nenhum vídeo automático foi produzido."
        )

    current = load_review_workspace(
        tasks_root, task_id, state_materials or [], cache_dir=cache_dir,
    )
    paths = current["paths"]
    for item in imported:
        if item["local_file"] not in paths:
            raise ValueError("Mídia importada indisponível ou alterada.")
    assigned = []
    for i, scene in enumerate(scenes):
        # Rotation favors variety; the subject is named in each chosen file.
        item = imported[i % len(imported)]
        assigned.append({
            **{k: v for k, v in scene.items() if not k.startswith("editorial_")},
            "assigned_material_file": item["local_file"],
            "match_status": "term_match_unverified",
            "media_verified": False,
            "automated_identity_verified": False,
            "selection_basis": "commons_filename_subject_match",
        })
    # No editorial_review field: this report MUST NOT claim human approval.
    preview = {
        "version": 1, "status": "machine_screened_not_human_reviewed",
        "scene_count": len(assigned), "scenes": assigned,
        "alignment": ws["preview"].get("alignment", "estimated"),
    }
    timeline = rick_scene_timeline.build_scene_render_preflight(
        preview, [paths[item["local_file"]] for item in imported],
        planned, max_clip_seconds=max_clip,
    )
    if timeline["status"] != "ready_metadata_only":
        raise ValueError("A sequência automática não passou na verificação de cenas.")

    directory = folder / "rick_auto_exports"
    if directory.is_symlink():
        raise ValueError("Pasta de exportação não autorizada.")
    directory.mkdir(exist_ok=True)
    if directory.resolve().parent != folder.resolve():
        raise ValueError("Pasta de exportação fora da tarefa.")

    run_id = uuid4().hex[:12]
    combined = directory / f"rick-auto-{run_id}-combined.mp4"
    output = directory / f"rick-auto-{run_id}-final.mp4"
    report_path = directory / f"rick-auto-{run_id}-report.json"
    used: list[str] = []
    params = _render_params(
        manifest, include_subtitles=subtitle is not None, clip_seconds=max_clip
    )
    video.combine_videos(
        combined_video_path=str(combined),
        video_paths=[paths[item["local_file"]] for item in imported],
        audio_file=str(audio),
        video_aspect=VideoAspect.portrait,
        video_concat_mode=VideoConcatMode.sequential,
        video_transition_mode=None,
        max_clip_duration=max_clip,
        video_fit_mode=params.video_fit_mode,
        clip_speed=1.0,
        threads=2, scene_timeline=timeline,
        used_video_paths=used,
    )
    video.generate_video(
        video_path=str(combined), audio_path=str(audio),
        subtitle_path=str(subtitle) if subtitle else "",
        output_file=str(output),
        params=params,
        bgm_file_override="",
    )
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("A exportação automática não gerou um MP4 válido.")

    report = {
        "version": 1,
        "status": "rendered_from_machine_screened_commons",
        "task_id": task_id,
        "output_filename": output.name,
        "scene_count": len(scenes),
        "image_count": len(imported),
        "used_source_basenames": [Path(path).name for path in used],
        "scene_assignments": [
            {
                "scene_number": index,
                "assigned_file": scene["assigned_material_file"],
                "text": str(scene.get("text") or "")[:160],
            }
            for index, scene in enumerate(assigned, 1)
        ],
        "subject_metadata_anchor": historical_person,
        "human_reviewed": False,
        "license_metadata_screened": True,
        "rights_legally_verified": False,
        "visual_identity_verified": False,
        "no_publication": True,
        "alignment": "estimated",
        "sources": [
            {
                "local_file": item["local_file"],
                "title": item["title"],
                "source_page": item["source_page"],
                "license": item["license"],
                "author_metadata": item["author_metadata"],
                "selection_basis": item["selection_basis"],
            }
            for item in imported
        ],
        "warnings": [
            "Associação por nome do arquivo; não comprova identidade nem veracidade da fotografia.",
            "Licenças filtradas por metadados; pode ser necessário conferir restrições adicionais.",
            "Intervalos de cenas estimados; fotos podem ser reutilizadas ao longo do vídeo.",
            "Original, revisão humana e estado da tarefa não foram modificados.",
        ],
    }
    temp = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=directory, mode="w", encoding="utf-8",
            prefix=".rick-auto-report-", suffix=".tmp", delete=False,
        ) as stream:
            temp = Path(stream.name)
            json.dump(report, stream, ensure_ascii=False, indent=2)
        os.replace(temp, report_path)
        temp = None
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return {"output": str(output), "report": str(report_path), **report}
