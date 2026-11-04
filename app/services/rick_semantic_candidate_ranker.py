"""Conservative scene-level ranking of independently reviewed alternatives.

Metadata may break ties between direct AI observations; metadata alone
NEVER makes a candidate recommended. Recommendations are human-review
leads, not approval, confirmation of copyright or permission to publish.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping


def rank_semantic_alternatives(
    compared: list[dict],
    targets: list[int],
) -> list[dict]:
    """Return one human-review recommendation at most per target scene.

    The assessment is a hypothesis based on up to two sampled frames.
    An ambiguous, failed, contextual or metaphorical comparison cannot
    become a recommended replacement, irrespective of metadata score.
    """
    grouped: dict[int, list[dict]] = defaultdict(list)
    expected = set(targets)
    for row in compared:
        if not isinstance(row, Mapping):
            continue
        number = row.get("scene_number")
        if type(number) is int and number in expected:
            grouped[number].append(dict(row))

    ranked: list[dict] = []
    for number in targets:
        candidates = grouped[number]
        direct = [
            row for row in candidates
            if row.get("status") == "ai_assessment_for_human_review"
            and row.get("verdict") == "plausible"
            and row.get("visual_relation") == "direct"
            and isinstance(row.get("visible_evidence"), str)
            and row["visible_evidence"].strip()
            and isinstance(row.get("file"), str)
            and row["file"]
        ]
        direct.sort(key=lambda row: (
            -(float(row.get("metadata_score", 0))
              if isinstance(row.get("metadata_score"), (float, int))
              and not isinstance(row.get("metadata_score"), bool)
              else 0),
            row["file"],
        ))
        candidate = direct[0] if direct else None
        ranked.append({
            "scene_number": number,
            "candidates_examined": len(candidates),
            "direct_candidates": len(direct),
            "suggested_file": candidate["file"] if candidate else None,
            "status": (
                "candidato_para_revisao_humana"
                if candidate else "sem_correspondencia_direta_demonstrada"
            ),
            "basis": (
                "observacao_visual_direta_ia_nao_homologada"
                if candidate else "nenhuma_alternativa_com_evidencia_direta"
            ),
            "human_approved": False,
            "license_verified": False,
            "auto_selection_permitted": False,
            "publishing_permitted": False,
        })
    return ranked
