"""Human-in-the-loop curation of Rick scenes, fully offline.

A search term and a filename do not establish what the media shows.
This module creates a review checklist and applies explicitly confirmed
choices. It NEVER claims automated person/object identification.

The resulting candidate preview remains compatible with the existing
rick_scene_timeline preflight; this module does not change rendering.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import re
from collections import Counter
from pathlib import PurePath
from typing import Any, Mapping, Sequence

MAX_SCENES = 60
MAX_TEXT_LENGTH = 8000
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


def _safe_name(value: Any) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 255:
        return None
    if any(marker in value for marker in ("/", "\\", "\x00")):
        return None
    if value in (".", "..") or PurePath(value).suffix.lower() not in _VIDEO_EXTENSIONS:
        return None
    return value


def _preview_scenes(preview: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if not isinstance(preview, Mapping):
        raise ValueError("Prévia de cenas ausente ou inválida")
    scenes = preview.get("scenes")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= MAX_SCENES:
        raise ValueError("O plano precisa conter entre 1 e 60 cenas")
    if preview.get("scene_count", len(scenes)) != len(scenes):
        raise ValueError("O número de cenas do plano não corresponde")
    if any(not isinstance(scene, Mapping) for scene in scenes):
        raise ValueError("Cena com formato inválido")
    return scenes


def plan_fingerprint(preview: Mapping[str, Any]) -> str:
    """Bind decisions to a specific immutable narration/scene plan.

    Deliberately exclude diagnostic counters and approved fields so applying
    a review does not change its fingerprint.
    """
    scenes = _preview_scenes(preview)
    keys = ("number", "start_seconds", "end_seconds", "text",
            "search_term")
    stable = [{key: scene.get(key) for key in keys} for scene in scenes]
    raw = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_review(preview: Mapping[str, Any]) -> dict[str, Any]:
    """Create a completely unapproved checklist; never auto-approve stock."""
    scenes = _preview_scenes(preview)
    entries = []
    for index, scene in enumerate(scenes, 1):
        entries.append({
            "scene_number": index,
            "approved": False,
            "file": scene.get("assigned_material_file") or "",
            "source_url": "",
            "credit": "",
            "license": "",
            "editor_note": "",
        })
    return {
        "version": 1,
        "plan_fingerprint": plan_fingerprint(preview),
        "scenes": entries,
        "instructions": (
            "Revise cada cena; marque approved=true somente após assistir à "
            "mídia e conferir o contexto. Registro de fonte e licença é "
            "uma declaração do revisor, não uma checagem automática."
        ),
    }


def apply_review(
    preview: Mapping[str, Any],
    review: Mapping[str, Any],
    available_files: Sequence[str],
) -> dict[str, Any]:
    """Require explicit approval and a unique local video for every scene.

    Returns a blocked status with no accepted preview when any scene fails,
    preventing partial reviews from accidentally reaching the renderer.
    """
    scenes = _preview_scenes(preview)
    if not isinstance(review, Mapping) or review.get("version") != 1:
        raise ValueError("Revisão precisa ter versão 1")
    if review.get("plan_fingerprint") != plan_fingerprint(preview):
        raise ValueError("Revisão desatualizada: roteiro ou divisão de cenas mudou")
    decisions = review.get("scenes")
    if not isinstance(decisions, list) or len(decisions) != len(scenes):
        raise ValueError("A revisão deve conter exatamente uma decisão por cena")
    if isinstance(available_files, (str, bytes)) or not isinstance(available_files, Sequence):
        raise ValueError("available_files precisa ser uma lista de caminhos")
    names = [
        item.replace("\\", "/").rsplit("/", 1)[-1]
        for item in available_files if isinstance(item, str)
    ]
    counts = Counter(names)
    blockers = []
    curated_scenes = []

    for index, (scene, decision) in enumerate(zip(scenes, decisions), start=1):
        if not isinstance(decision, Mapping) or decision.get("scene_number") != index:
            raise ValueError("Decisões fora da ordem das cenas")
        filename = _safe_name(decision.get("file"))
        if decision.get("approved") is not True:
            blockers.append({"scene_number": index, "code": "editor_approval_missing"})
        if filename is None or counts[filename] != 1:
            blockers.append({"scene_number": index, "code": "review_asset_unavailable"})

        original = scene.get("assigned_material_file")
        is_replacement = filename is not None and filename != original
        metadata = {}
        for key in ("source_url", "credit", "license"):
            value = decision.get(key, "")
            if not isinstance(value, str) or len(value) > 1000:
                raise ValueError(f"Campo de origem inválido: {key}")
            metadata[key] = value.strip()
        if is_replacement and not all(metadata.values()):
            blockers.append({"scene_number": index, "code": "replacement_provenance_missing"})
        if metadata["source_url"] and not re.match(
            r"^https?://[^\s<>\"']+$", metadata["source_url"], re.IGNORECASE
        ):
            blockers.append({"scene_number": index, "code": "invalid_source_url"})

        updated = copy.deepcopy(scene)
        updated["assigned_material_file"] = filename
        updated["match_status"] = "term_match_unverified" if filename and counts[filename] == 1 else "missing_term_match"
        updated["editor_approved"] = decision.get("approved") is True
        updated["editor_replaced_material"] = is_replacement
        updated["editor_source_reference"] = metadata
        updated["media_verified"] = False
        curated_scenes.append(updated)

    if blockers:
        return {"version": 1, "status": "blocked", "blockers": blockers,
                "approved_preview": None, "media_verified": False}
    accepted = copy.deepcopy(dict(preview))
    accepted["scenes"] = curated_scenes
    accepted["scenes_with_term_candidate"] = len(scenes)
    accepted["scenes_without_term_candidate"] = 0
    accepted["status"] = "reviewed_by_operator"
    accepted["source_media_verified"] = False
    accepted["editor_review_fingerprint"] = review["plan_fingerprint"]
    accepted["warnings"] = [
        *accepted.get("warnings", []),
        {"code": "manual_review_not_authenticity_check",
         "message": "Revisão humana não substitui verificação independente da fonte e dos direitos."},
    ]
    return {"version": 1, "status": "approved", "blockers": [],
            "approved_preview": accepted, "media_verified": False}


def render_review_html(preview: Mapping[str, Any], review: Mapping[str, Any]) -> str:
    """Offline, dependency-free HTML checklist; escape all untrusted text."""
    scenes = _preview_scenes(preview)
    decisions = review.get("scenes")
    if not isinstance(decisions, list) or len(decisions) != len(scenes):
        raise ValueError("Revisão incompatível com as cenas")
    e = lambda value: html.escape(str(value if value is not None else ""), quote=True)
    cards = []
    for index, (scene, decision) in enumerate(zip(scenes, decisions), 1):
        text = str(scene.get("text") or "")[:MAX_TEXT_LENGTH]
        status = "Aprovada" if decision.get("approved") is True else "Pendente"
        cards.append(
            '<article><h2>Cena ' + str(index) + ' — ' + e(status) + '</h2>'
            '<p><strong>Intervalo estimado:</strong> ' + e(scene.get("start_seconds"))
            + '–' + e(scene.get("end_seconds")) + ' s</p>'
            '<p><strong>Narração:</strong> ' + e(text) + '</p>'
            '<p><strong>Busca original:</strong> ' + e(scene.get("search_term")) + '</p>'
            '<p><strong>Arquivo escolhido:</strong> ' + e(decision.get("file")) + '</p>'
            '<p><strong>Créditos:</strong> ' + e(decision.get("credit")) + '</p>'
            '<p><strong>Licença declarada:</strong> ' + e(decision.get("license")) + '</p>'
            '<p><strong>Referência:</strong> ' + e(decision.get("source_url")) + '</p>'
            '<p><strong>Notas:</strong> ' + e(decision.get("editor_note")) + '</p></article>'
        )
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Rick — Revisão das cenas</title><style>'
        'body{font:16px system-ui;background:#111722;color:#f4f7ff;margin:auto;max-width:880px;padding:24px}'
        'article{background:#222c3d;border:1px solid #4d5b6f;border-radius:12px;padding:18px;margin:16px 0}'
        'h1{font-size:26px}h2{font-size:21px}p{line-height:1.5;overflow-wrap:anywhere}'
        '.notice{color:#ffcf86}</style></head><body>'
        '<h1>Rick — Revisão editorial por cena</h1>'
        '<p class="notice">Este relatório não autentica pessoas, datas, autoria ou licença. '
        'Verifique a mídia original antes de aprovar. Edite o JSON de revisão; '
        'este HTML é apenas uma ficha de leitura.</p>'
        + "".join(cards) + '</body></html>'
    )
