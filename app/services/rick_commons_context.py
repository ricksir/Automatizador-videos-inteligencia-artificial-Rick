"""Conservative Commons CC0/public-domain photo fallback by *scene context*.

Only fixed editorial categories are accepted; untrusted narration is never
used as a raw Commons search query. Filename and public-domain metadata are
merely screening signals, not proof of what pixels show, provenance or
publication rights. Search is explicit and capped, and no approval is saved.
"""
from __future__ import annotations

from typing import Any

from app.services.rick_auto_commons import (
    _commons_pages, _eligible_image, _normalized,
)

# Narrow, predictable filename tokens: no proper names or untrusted query
# strings. Prefer archival objects rather than generic landscape images.
_SCENE_TOPICS: dict[str, tuple[str, ...]] = {
    "institutions": ("parliament", "congress"),
    "elections": ("ballot", "voting"),
    "documents": ("manuscript", "newspaper"),
    "education": ("library", "university"),
    "demonstrations": ("protest", "demonstration"),
    "ideas": ("books", "discussion"),
}

_UNRELATED_TITLE_WORDS = frozenset({
    "waterfall", "cachoeira", "sunset", "beach", "forest",
    "football", "soccer", "advertisement", "commercial",
    "poster", "logo", "icon", "map", "cartoon", "illustration",
})

_BASE_PARAMS = {
    "action": "query",
    "generator": "search",
    "gsrnamespace": "6",
    "gsrlimit": "30",
    "prop": "imageinfo",
    "iiprop": "url|size|mime|extmetadata",
    "iiurlwidth": "900",
    "format": "json",
    "formatversion": "2",
}


def contextual_topics(kind: str) -> tuple[str, ...]:
    """Return only known, preapproved search terms."""
    return _SCENE_TOPICS.get(kind, ())


def find_contextual_commons_stills(
    kind: str, *, max_results: int = 2,
) -> list[dict[str, Any]]:
    """Search at most two bounded API queries for filename-matching photos.

    Failures in one query do not stop a second safe query. The caller
    decides whether to continue with other sources and records errors.
    """
    if (
        kind not in _SCENE_TOPICS
        or type(max_results) is not int
        or not 1 <= max_results <= 4
    ):
        raise ValueError("Categoria de fotografia contextual inválida.")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    failed_searches = 0
    for term in _SCENE_TOPICS[kind]:
        if len(results) >= max_results:
            break
        try:
            pages, _ = _commons_pages({
                **_BASE_PARAMS, "gsrsearch": f"intitle:{term}",
            })
        except (RuntimeError, ValueError, OSError):
            failed_searches += 1
            continue
        if not isinstance(pages, list):
            continue
        for page in pages:
            item = _eligible_image(page, term)
            if not item:
                continue
            # Avoid substring matches: "books" must be an actual filename word,
            # not part of a location, handle or organization name.
            title = str(item.get("title") or "")
            tokens = set(_normalized(title).split())
            if term not in tokens or tokens & _UNRELATED_TITLE_WORDS:
                continue
            url = item["source_page"]
            if url in seen:
                continue
            seen.add(url)
            results.append({
                **item,
                "context_kind": kind,
                "context_keyword": term,
                "selection_basis": "filename_context_word_and_pd_cc0_metadata",
                "visually_verified": False,
                "rights_verified": False,
            })
            if len(results) >= max_results:
                break
    if not results and failed_searches == len(_SCENE_TOPICS[kind]):
        raise RuntimeError("Todas as pesquisas contextuais do Commons falharam.")
    return results
