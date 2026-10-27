"""Offline editorial triage for Rick short videos.

No AI, network, image recognition, licence verification or external downloads.
Metadata is useful for deciding what to inspect, never proof of a visual match.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from urllib.parse import urlencode

_PERSON_TITLE = re.compile(
    r"\\b(?:fil[oó]sof[oa]|cientista|historiador(?:a)?|escritor(?:a)?|"
    r"presidente|pol[ií]tic[oa]|pintor(?:a)?|m[uú]sic[oa]|autor(?:a)?)"
    r"\\s+([a-zà-ÿ]{4,})(?:\\s+([a-zà-ÿ]{4,}))?",
    flags=re.IGNORECASE,
)
_STOP = frozenset({
    "a", "o", "as", "os", "e", "do", "da", "dos", "das", "de", "um", "uma",
    "que", "como", "sobre", "seu", "sua", "livro", "teoria", "brasil",
    "quem", "foi", "tem", "com", "para", "por", "no", "na", "em", "ao",
    "eleicao", "eleições", "sociedade", "filosofo", "study", "theory",
    "video", "photo", "image", "stock", "portrait",
})
_WORD = re.compile(r"[^\W_]+", flags=re.UNICODE)


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(_WORD.findall(text))


def person_anchor(subject: str) -> str | None:
    """Conservative lexical clue; not a claim that a person was identified."""
    if not isinstance(subject, str):
        return None
    match = _PERSON_TITLE.search(subject[:500])
    if not match:
        return None
    first = match.group(1)
    second = match.group(2)
    if _norm(first) in _STOP:
        return None
    # A second word is accepted only if explicitly capitalized in the
    # subject; otherwise it can be a verb ("Gramsci estudou").
    if second and second[0].isupper() and _norm(second) not in _STOP:
        return f"{first} {second}".title()
    return first.title()


def commons_search_url(query: str) -> str:
    """A link only; never fetches media or assumes a Commons licence."""
    if not isinstance(query, str):
        raise ValueError("query must be text")
    clean = " ".join(query.split())[:120]
    if not clean:
        raise ValueError("empty search query")
    return "https://commons.wikimedia.org/w/index.php?" + urlencode({
        "title": "Special:MediaSearch",
        "type": "image",
        "search": clean,
    })


def inspect_visual_scenes(
    subject: str,
    scenes: Sequence[Mapping],
    material_sources: Sequence[Mapping],
) -> dict:
    """Return bounded, transparent hints for human editorial review.

    Checks search metadata and repeated sources only. Does NOT inspect pixels,
    detect people, fact-check, validate usage rights or select media.
    """
    if not isinstance(scenes, (list, tuple)) or len(scenes) > 60:
        raise ValueError("scenes must be a bounded list")
    if not isinstance(material_sources, (list, tuple)):
        raise ValueError("material_sources must be a list")
    anchor = person_anchor(subject)
    by_name = {}
    for record in material_sources[:250]:
        if not isinstance(record, Mapping):
            continue
        name = record.get("local_file")
        if isinstance(name, str) and "/" not in name and "\\" not in name and name not in by_name:
            by_name[name] = record
    usage = Counter()
    rows = []
    for index, scene in enumerate(scenes, 1):
        if not isinstance(scene, Mapping):
            raise ValueError("invalid scene")
        name = scene.get("assigned_material_file")
        if isinstance(name, str) and name in by_name:
            identity_record = by_name[name]
            identity = (
                str(identity_record.get("provider", "")).casefold(),
                str(identity_record.get("asset_id") or name),
            )
            usage[identity] += 1
        else:
            name = None
        term = scene.get("search_term")
        term = str(term).strip()[:150] if isinstance(term, str) else ""
        issues = []
        if not name:
            issues.append("sem candidato correspondente no manifesto")
        if scene.get("material_reused") is True:
            issues.append("reutilização de origem")
        if anchor and anchor.casefold() in str(scene.get("text") or "").casefold():
            if not term or _norm(anchor) not in _norm(term):
                issues.append("nome citado na narração ausente da busca")
        if anchor and name:
            registered_term = by_name[name].get("search_term")
            if not isinstance(registered_term, str) or _norm(anchor) not in _norm(registered_term):
                issues.append("metadados não demonstram presença da pessoa")
        queries = []
        if anchor:
            queries.extend([f"{anchor} portrait", f"{anchor} historical photograph"])
        if term:
            queries.append(term)
        if not queries:
            snippet = " ".join(_WORD.findall(str(scene.get("text") or ""))[:5])
            if snippet:
                queries.append(snippet)
        queries = list(dict.fromkeys(queries))[:3]
        row = {
            "scene_number": index,
            "text": str(scene.get("text") or "")[:250],
            "search_term": term,
            "candidate": name,
            "issues": issues,
            "review_required": True,
            "suggested_queries": queries,
            "historical_image_search_url": commons_search_url(
                queries[0]
            ) if anchor and queries else None,
        }
        rows.append(row)
    return {
        "version": 1,
        "subject_anchor": anchor,
        "scenes_total": len(rows),
        "scenes_with_issues": sum(bool(x["issues"]) for x in rows),
        "unique_source_identities": len(usage),
        "reused_source_occurrences": sum(max(0, count - 1) for count in usage.values()),
        "scenes": rows,
        "disclaimer": (
            "Triagem por metadados e palavras do roteiro. Não verifica pixels, "
            "identidade, fatos, licença nem alinhamento real. "
            "Imagens do Wikimedia Commons exigem conferência de licença."
        ),
    }


def retained_human_decisions(saved_scenes: Sequence[Mapping], *,
                             exclude_scene: int | None = None) -> list[dict]:
    """Preserve previously saved decisions when editing only one scene.

    Passing them back through build_editorial_review forces revalidation.
    No inference from automatic candidates to approved choices is permitted.
    """
    if not isinstance(saved_scenes, (list, tuple)):
        return []
    decisions = []
    for number, scene in enumerate(saved_scenes[:60], 1):
        if number == exclude_scene or not isinstance(scene, Mapping):
            continue
        status = scene.get("editorial_review")
        if status == "rejected":
            decisions.append({"scene_number": number, "decision": "reject"})
        elif status == "approved_by_human":
            decisions.append({
                "scene_number": number,
                "decision": "approve",
                "selected_file": scene.get("assigned_material_file"),
                "source_note": scene.get("editorial_source_note"),
                "content_checked": scene.get("editorial_content_checked") is True,
                "rights_checked": scene.get("editorial_rights_checked") is True,
            })
    return decisions
