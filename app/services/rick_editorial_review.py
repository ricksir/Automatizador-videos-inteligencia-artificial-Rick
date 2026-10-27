"""Offline human editorial review gate for Rick scene candidates.

An exact search-term match is NOT image verification. This pure module
collects human decisions and records which existing downloaded asset can be
used for each scene. It has no network, AI, downloads, file IO or automation.
Nothing here recognizes a person or authenticates a historic photograph.
"""
from __future__ import annotations

from collections import Counter
from pathlib import PurePath
from typing import Any, Mapping, Sequence

MAX_SCENES = 60
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


def _filename(raw: Any) -> str | None:
    if (not isinstance(raw, str) or not raw or "\x00" in raw
            or "/" in raw or "\\" in raw or raw in {".", ".."}):
        return None
    return raw if PurePath(raw).suffix.lower() in ALLOWED_EXTENSIONS else None


def _name(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def build_editorial_review(
    preview: Mapping[str, Any],
    downloaded_files: Sequence[str],
    decisions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build candidate preview with optional *explicit* human-approved overrides.

    Decision record: {scene_number: int, decision: "approve" | "reject",
    selected_file: basename (required if approved), source_note: nonempty text,
    rights_checked: True, content_checked: True}.

    source_note is a reviewer-supplied provenance explanation, not independently
    verified. Reject all invalid or ambiguous files and every unreviewed scene.
    """
    if not isinstance(preview, Mapping):
        raise ValueError("preview must be an object")
    scenes = preview.get("scenes")
    if not isinstance(scenes, list) or not (1 <= len(scenes) <= MAX_SCENES):
        raise ValueError("preview must have 1..60 scenes")
    if isinstance(downloaded_files, (str, bytes)) or not isinstance(downloaded_files, Sequence):
        raise ValueError("downloaded_files must be a sequence")
    if isinstance(decisions, (str, bytes)) or not isinstance(decisions, Sequence):
        raise ValueError("decisions must be a sequence")

    counts = Counter(
        _name(path) for path in downloaded_files if isinstance(path, str)
    )
    by_scene: dict[int, Mapping[str, Any]] = {}
    for decision in decisions:
        if not isinstance(decision, Mapping):
            raise ValueError("decisions must be objects")
        number = decision.get("scene_number")
        if type(number) is not int or number < 1 or number > len(scenes):
            raise ValueError("invalid decision scene number")
        if number in by_scene:
            raise ValueError("duplicate decision for a scene")
        if decision.get("decision") not in ("approve", "reject"):
            raise ValueError("decision must be approve or reject")
        by_scene[number] = decision

    approved = []
    blockers = []
    reviewed_scenes = []
    for index, scene in enumerate(scenes, 1):
        if not isinstance(scene, Mapping):
            raise ValueError("scene must be an object")
        result = dict(scene)
        decision = by_scene.get(index)
        result.update({
            "editorial_review": "unreviewed",
            "editorial_source_note": None,
            "editorial_rights_checked": False,
            "editorial_content_checked": False,
            # Candidate suggestions must never be mistaken for approved files.
            "assigned_material_file": None,
            "match_status": "editorial_review_required",
        })
        if decision is None:
            blockers.append({"scene_number": index, "code": "review_missing"})
        elif decision["decision"] == "reject":
            result["assigned_material_file"] = None
            result["match_status"] = "editorial_rejected"
            result["editorial_review"] = "rejected"
            blockers.append({"scene_number": index, "code": "review_rejected"})
        else:
            filename = _filename(decision.get("selected_file"))
            note = decision.get("source_note")
            if not filename or counts[filename] != 1:
                blockers.append({"scene_number": index, "code": "file_missing_or_ambiguous"})
            elif not isinstance(note, str) or not note.strip():
                blockers.append({"scene_number": index, "code": "provenance_note_missing"})
            elif decision.get("rights_checked") is not True:
                blockers.append({"scene_number": index, "code": "rights_review_missing"})
            elif decision.get("content_checked") is not True:
                blockers.append({"scene_number": index, "code": "content_review_missing"})
            else:
                result["assigned_material_file"] = filename
                result["match_status"] = "term_match_unverified"
                result["editorial_review"] = "approved_by_human"
                result["editorial_source_note"] = note.strip()
                result["editorial_rights_checked"] = True
                result["editorial_content_checked"] = True
                approved.append(index)
        result["media_verified"] = False
        # Review of source / representation is a recorded claim by the user,
        # not automated identity or copyright verification.
        result["automated_identity_verified"] = False
        reviewed_scenes.append(result)

    return {
        "version": 1,
        "status": "ready_human_reviewed" if not blockers else "blocked",
        "scene_count": len(scenes),
        "human_approved_count": len(approved),
        "scenes": reviewed_scenes,
        "blockers": blockers,
        "alignment": preview.get("alignment", "estimated"),
        "visual_identity_verified_automatically": False,
        "rights_verified_automatically": False,
        "warning": "Declarações de revisão humana; o software não autentica identidade, origem ou licenças.",
    }
