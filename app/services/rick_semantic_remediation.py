"""Opt-in discovery and Gemini re-evaluation of *alternative* scene media.

A bad visual verdict can nominate a scene for bounded candidate discovery.
The original proposal, human editorial choices, saved MP4 and publication
state are NEVER changed. New assets join only the review inventory.
A new candidate receives a second, fallible Gemini opinion; no result is
presented as editorial or legal approval.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from app.services.rick_editorial_workspace import load_review_workspace
from app.services.rick_scene_precuration import _score, scene_search_context
from app.services.rick_semantic_frame_review import review_scene_frames

_MAX_TARGETS = 3
_MIN_METADATA_SCORE = 40


def _problem_scenes(
    semantic: Mapping,
    proposals: Mapping,
    *,
    model: str,
    saved_review: Mapping | None,
    max_scenes: int,
) -> list[int]:
    """Select only currently unmatched/uncertain AI assessments, not stale ones."""
    if (
        semantic.get("version") != 2
        or semantic.get("model") != model
        or not isinstance(semantic.get("results"), list)
        or not isinstance(proposals.get("scenes"), list)
    ):
        raise ValueError("Reavaliação antiga ou incompatível com a tarefa.")
    by_number = {
        r.get("scene_number"): r
        for r in proposals["scenes"]
        if isinstance(r, Mapping) and type(r.get("scene_number")) is int
    }
    human = {}
    if isinstance(saved_review, Mapping):
        saved = saved_review.get("scenes", [])
        if isinstance(saved, list):
            human = {
                index: value
                for index, value in enumerate(saved, 1)
                if isinstance(value, Mapping)
            }
    targets: list[int] = []
    for result in semantic["results"][:6]:
        if not isinstance(result, Mapping):
            continue
        number = result.get("scene_number")
        scene = by_number.get(number)
        if (
            not scene or type(number) is not int
            or number in targets
            or result.get("status") != "ai_assessment_for_human_review"
            or result.get("file") != scene.get("primary")
        ):
            continue
        if human.get(number, {}).get("editorial_review") == "approved_by_human":
            continue
        if (
            result.get("verdict") == "plausible"
            and result.get("visual_relation") == "direct"
        ):
            continue
        targets.append(number)
        if len(targets) >= max_scenes:
            break
    return targets


def _candidate_alternatives(
    workspace: Mapping,
    *,
    original_proposals: Mapping,
    subject: str,
    targets: list[int],
) -> tuple[dict[int, dict], list[dict]]:
    """Pick one *new-to-this-scene* alternative per target, metadata only.

    Sources are restricted to the task-controlled, verified inventory;
    score is a routing signal, not a probability or visual endorsement.
    """
    preview_scenes = workspace["preview"]["scenes"]
    meta = workspace["source_metadata"]
    paths = workspace["paths"]
    old = {
        item["scene_number"]: item for item in original_proposals["scenes"]
        if isinstance(item, Mapping) and type(item.get("scene_number")) is int
    }
    reserved: Counter[str] = Counter()
    candidate_map: dict[int, dict] = {}
    misses: list[dict] = []
    for number in targets:
        scene = preview_scenes[number - 1]
        intent = scene_search_context(preview_scenes, number - 1, subject)
        ranked: list[dict] = []
        for name in sorted(paths):
            if name == old[number].get("primary") or name not in meta:
                continue
            row = _score({**scene, "number": number}, intent, name, meta[name])
            if row["score"] >= _MIN_METADATA_SCORE:
                ranked.append(row)
        ranked.sort(key=lambda row: (
            reserved[row["name"]] >= 2,
            reserved[row["name"]],
            -row["score"],
            row["name"],
        ))
        candidate = next(
            (r for r in ranked if reserved[r["name"]] < 2), None
        )
        if candidate is None:
            misses.append({
                "scene_number": number, "status": "sem_alternativa_com_metadados",
            })
            continue
        reserved[candidate["name"]] += 1
        candidate_map[number] = candidate
    return candidate_map, misses


def run_semantic_remediation(
    tasks_root: str | Path,
    task_id: str,
    state_materials: list[str],
    *,
    original_proposals: Mapping,
    semantic_assessment: Mapping,
    subject: str,
    api_key: str,
    model: str,
    consent: bool,
    audio_duration: object = None,
    cache_dir: str | Path | None = None,
    discover: bool = True,
    max_scenes: int = 3,
) -> dict:
    """Search and re-evaluate up to 3 problematic scenes on a direct click.

    Network use: optional bounded provider lookups + max three Gemini calls.
    No persisted change to scene selection or human decision is performed.
    """
    if consent is not True:
        raise ValueError("consent_required")
    if (
        not isinstance(original_proposals, Mapping)
        or not isinstance(semantic_assessment, Mapping)
        or not isinstance(state_materials, list)
        or not isinstance(subject, str) or len(subject) > 500
        or not isinstance(api_key, str) or not api_key.strip()
        or not isinstance(model, str) or not model.strip()
        or type(discover) is not bool
        or type(max_scenes) is not int or not 1 <= max_scenes <= _MAX_TARGETS
    ):
        raise ValueError("Dados de recuperação semântica inválidos.")

    workspace = load_review_workspace(
        tasks_root, task_id, state_materials,
        audio_duration=audio_duration, cache_dir=cache_dir,
    )
    preview_scenes = workspace["preview"]["scenes"]
    old_scenes = original_proposals.get("scenes")
    if (
        not isinstance(old_scenes, list)
        or len(old_scenes) != len(preview_scenes)
        or any(
            not isinstance(row, Mapping)
            or row.get("text") != preview_scenes[i].get("text")
            or row.get("scene_number") != i + 1
            for i, row in enumerate(old_scenes)
        )
    ):
        raise ValueError("Pré-curadoria desatualizada: atualize a tarefa.")

    targets = _problem_scenes(
        semantic_assessment, original_proposals,
        model=model, saved_review=workspace["saved_review"],
        max_scenes=max_scenes,
    )
    discovery = None
    if discover and targets:
        from app.services.rick_scene_discovery import discover_scene_media

        discovery = discover_scene_media(
            tasks_root, task_id, subject=subject,
            scenes=preview_scenes, source_metadata=workspace["source_metadata"],
            priority_scene_numbers=targets, priority_only=True,
            max_stills=4, max_clips=3, search_variants=True,
            search_context_photos=True,
        )
        workspace = load_review_workspace(
            tasks_root, task_id, state_materials,
            audio_duration=audio_duration, cache_dir=cache_dir,
        )

    candidates, misses = _candidate_alternatives(
        workspace, original_proposals=original_proposals,
        subject=subject, targets=targets,
    )
    if candidates:
        # Include all scene text for sentence continuity. ONLY target
        # alternatives have a primary: other scenes cannot consume API quota.
        review_scenes = [
            {
                "scene_number": i,
                "text": str(scene.get("text") or "")[:250],
                "primary": candidates.get(i, {}).get("name"),
            }
            for i, scene in enumerate(preview_scenes, 1)
        ]
        assessed = review_scene_frames(
            {"scenes": review_scenes}, workspace["paths"],
            subject=subject, api_key=api_key, model=model,
            consent=consent, max_scenes=max_scenes,
        )
    else:
        assessed = {
            "version": 2, "model": model, "results": [],
            "api_requests": 0, "assessed": 0,
        }

    comparisons = []
    original_by_number = {
        row["scene_number"]: row for row in original_proposals["scenes"]
    }
    for row in assessed.get("results", []):
        number = row["scene_number"]
        proposed = candidates[number]
        source = workspace["source_metadata"].get(row["file"], {})
        comparisons.append({
            **row,
            "original_file": original_by_number[number]["primary"],
            "metadata_score": proposed["score"],
            "source_page": str(source.get("source_page") or "")[:400],
            "license_metadata": str(
                source.get("license") or source.get("source_note") or ""
            )[:250],
            "selected_as_primary": False,
            "rights_verified": False,
        })

    return {
        "version": 1,
        "targets": targets,
        "discovery": discovery,
        "compared": comparisons,
        "unresolved": misses,
        "api_requests": assessed["api_requests"],
        "ai_assessed": assessed["assessed"],
        "original_proposals_unchanged": True,
        "human_approved": False,
        "publishing_permitted": False,
        "note": (
            "Novos arquivos foram adicionados apenas ao inventário. "
            "Nenhum candidato foi automaticamente selecionado, aprovado "
            "ou publicado. Confirme pertinência real e direitos de uso."
        ),
    }
