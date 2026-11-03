"""Rick pre-curation: bounded, explainable, scene-specific *metadata* proposals.

This module does not inspect video pixels, recognize historical people, prove
licences, approve content, or publish. A numeric metadata score is NEVER
a calibrated confidence in visual correctness. Unmatched scenes are left
unresolved; do not fall back to generic or unrelated footage.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence

from app.services.rick_visual_curation import person_anchor

_STOP = frozenset({
    "a", "o", "as", "os", "do", "da", "dos", "das", "de", "e", "em",
    "um", "uma", "que", "com", "para", "por", "no", "na", "ao",
    "the", "of", "to", "and", "is", "in", "on", "image", "video",
    "photo", "footage", "stock", "file", "mp4", "jpg", "png",
})
_CONTEXTS = (
    ("elections", ("eleic", "vot", "urna", "eleitor", "election", "ballot"), "elections voting ballot people"),
    ("institutions", ("instituic", "parlament", "congres", "govern", "institut", "parliament"), "parliament government institutions"),
    ("demonstrations", ("protest", "manifest", "revoluc", "mobiliz", "demonstrat"), "civil demonstration public gathering"),
    ("documents", ("livro", "escrev", "jornal", "manuscr", "document", "bibliotec", "book"), "historical books documents manuscript"),
    ("education", ("estud", "univers", "escola", "educa", "aprend"), "historical study books library"),
    ("ideas", ("ideia", "hegemon", "cultur", "narrativ", "simbol", "visao", "pensament", "theory"), "people discussing ideas books"),
)
_UNRELATED = frozenset({
    "waterfall", "cachoeira", "nature", "forest", "floresta",
    "beach", "praia", "landscape", "paisagem", "lake", "lago",
    "sunset", "pordosol", "wildlife", "animal",
})
_UNRELATED_FOR_PERSON = frozenset({
    "father", "mother", "parents", "family", "familia", "daughter",
    "son", "monument", "monumento", "street", "rua", "avenida",
    "square", "piazza", "memorial",
})


def _norm(text: object) -> str:
    value = unicodedata.normalize("NFKD", str(text or "").casefold())
    letters = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", letters))


def _words(text: object) -> set[str]:
    return set(_norm(text).split()) - _STOP


def scene_intent(scene: Mapping, subject: str = "") -> dict:
    """Identify narrow intent from the actual spoken excerpt, not video topic."""
    text = _norm(scene.get("text"))
    anchor = person_anchor(subject)
    named = bool(anchor and _norm(anchor) in text)
    context = "general"
    query = str(scene.get("search_term") or "").strip()[:120]
    for name, clues, english_query in _CONTEXTS:
        if any(clue in token for token in text.split() for clue in clues):
            context, query = name, english_query
            break
    if named and context in ("general", "education", "ideas", "documents"):
        context = "historical_person"
        query = f"{anchor} historical portrait photograph"
    if not query:
        query = " ".join(str(scene.get("text") or "").split()[:7])[:100]
    return {
        "kind": context,
        "person": anchor if named else None,
        "query": query,
        "text": str(scene.get("text") or "")[:250],
        "alignment": str(scene.get("alignment") or "estimated")[:40],
    }


def _score(scene: Mapping, intent: Mapping, name: str, meta: Mapping) -> dict:
    text_tokens = _words(scene.get("text"))
    term = _norm(meta.get("search_term"))
    note = _norm(meta.get("source_page"))
    title = _norm(meta.get("title"))
    label = " ".join([term, note, title, _norm(meta.get("asset_id"))])
    label_tokens = set(label.split())
    score = 0
    evidence = []
    search = _norm(scene.get("search_term"))
    if search and search == term:
        score += 30
        evidence.append("consulta_original_exata")
    overlap = text_tokens & label_tokens
    if overlap:
        score += min(len(overlap) * 9, 27)
        evidence.append("termos_da_fala_nos_metadados")
    intent_kind = intent["kind"]
    intent_query_tokens = _words(intent["query"])
    relevant = len(intent_query_tokens & label_tokens)
    if relevant:
        score += min(12 * relevant, 36)
        evidence.append("contexto_de_cena_nos_metadados")
    source_scene = meta.get("scene_number")
    if (type(source_scene) is int and source_scene == scene.get("number")):
        score += 30
        evidence.append("material_adicionado_para_esta_cena")
    person = intent.get("person")
    if person:
        # A query bearing the name can reference unrelated material (e.g.
        # Gramsci Brazil -> waterfall). Require filename/source-page/title
        # evidence, or an explicit scene-specific local import.
        person_evidence = _norm(person) in (" ".join([title, note, _norm(name)]))
        if person_evidence:
            score += 35
            evidence.append("pessoa_nomeada_no_titulo_ou_origem")
        elif source_scene != scene.get("number"):
            score = min(score, 20)
            evidence.append("pessoa_sem_evidencia_de_imagem")
    if intent_kind == "historical_person":
        mismatch = _UNRELATED_FOR_PERSON & label_tokens
        if mismatch or (_UNRELATED & label_tokens):
            return {"name": name, "score": 0, "reasons": ["conteudo_descrito_inadequado"]}
    if _UNRELATED & label_tokens and intent_kind != "general":
        return {"name": name, "score": 0, "reasons": ["natureza_sem_relacao_com_a_fala"]}
    if intent_kind in ("elections", "institutions", "demonstrations"):
        strong = any(clue in label for clue in _words(intent["query"]))
        if not strong:
            score = min(score, 25)
    # A declared provider or task-local file is a traceable starting point,
    # not legal certification of rights.
    if meta.get("provider") and meta.get("source_page"):
        score += 4
    return {"name": name, "score": min(score, 95), "reasons": evidence}


def build_precuration(
    subject: str,
    scenes: Sequence[Mapping],
    source_metadata: Mapping[str, Mapping],
    available_names: Sequence[str],
    *,
    max_uses: int = 2,
    min_score: int = 40,
) -> dict:
    """Select one primary + up to two backups per scene, with reuse limits.

    All choices remain *proposals* requiring visual and rights verification.
    """
    if (not isinstance(scenes, (list, tuple)) or not 1 <= len(scenes) <= 60
            or not isinstance(source_metadata, Mapping)
            or not isinstance(available_names, (list, tuple))
            or type(max_uses) is not int or not 1 <= max_uses <= 3
            or type(min_score) is not int or not 1 <= min_score <= 95):
        raise ValueError("Dados de pré-curadoria inválidos.")
    names = sorted({n for n in available_names if isinstance(n, str) and n in source_metadata})
    used: Counter[str] = Counter()
    result = []
    for i, scene in enumerate(scenes, 1):
        if not isinstance(scene, Mapping):
            raise ValueError("Cena de pré-curadoria inválida.")
        numbered = {**scene, "number": i}
        intent = scene_intent(scene, subject)
        candidates = [
            _score(numbered, intent, name, source_metadata.get(name, {}))
            for name in names
        ]
        candidates.sort(key=lambda row: (-row["score"], used[row["name"]], row["name"]))
        eligible = [
            row for row in candidates
            if row["score"] >= min_score and used[row["name"]] < max_uses
        ]
        best = eligible[0] if eligible else None
        # Prevent adjacent repeats when another reasonable candidate exists.
        if best and result and best["name"] == result[-1]["primary"]:
            alternative = next(
                (row for row in eligible if row["name"] != best["name"]), None
            )
            if alternative is not None:
                best = alternative
        if best:
            used[best["name"]] += 1
        backups = [
            {"file": row["name"], "metadata_score": row["score"],
             "reasons": row["reasons"]}
            for row in candidates
            if row["score"] >= min_score and (not best or row["name"] != best["name"])
        ][:2]
        result.append({
            "scene_number": i,
            "start_seconds": scene.get("start_seconds"),
            "end_seconds": scene.get("end_seconds"),
            "text": str(scene.get("text") or "")[:250],
            "intent": intent,
            "primary": best["name"] if best else None,
            "metadata_score": best["score"] if best else 0,
            "reasons": best["reasons"] if best else ["sem_candidato_elegivel"],
            "alternatives": backups,
            "status": "proposal_for_human_review" if best else "unresolved",
            "visual_content_verified": False,
            "rights_verified": False,
            "human_approved": False,
        })
    return {
        "version": 1,
        "status": "metadata_precuration_only",
        "scene_count": len(result),
        "proposed_count": sum(bool(r["primary"]) for r in result),
        "unresolved_count": sum(not r["primary"] for r in result),
        "unique_selected_files": len(used),
        "scenes": result,
        "warning": (
            "Pontuações são sinais de metadados, NÃO probabilidades de acerto "
            "visual. Sem verificação real de conteúdo, licença ou sincronização."
        ),
    }
