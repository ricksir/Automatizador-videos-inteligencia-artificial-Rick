"""Merge one explicit retry of failed semantic Gemini assessments.

No API calls or disk writes occur here. A failure may not overwrite a
previous successful evaluation, and the same file/model must still be used.
"""
from __future__ import annotations

from collections.abc import Mapping


def failed_scene_numbers(report: Mapping) -> list[int]:
    """Return only scenes with provider/invalid-response errors, maximum six."""
    if not isinstance(report, Mapping) or not isinstance(report.get("results"), list):
        return []
    return list(dict.fromkeys(
        r["scene_number"] for r in report["results"][:6]
        if isinstance(r, Mapping)
        and type(r.get("scene_number")) is int
        and r.get("status") == "provider_or_response_failure"
    ))


def merge_failed_scene_retry(previous: Mapping, retry: Mapping) -> dict:
    """Replace only a failed result for the same (scene number, media) pair."""
    if (
        not isinstance(previous, Mapping) or not isinstance(retry, Mapping)
        or previous.get("version") != 2 or retry.get("version") != 2
        or previous.get("model") != retry.get("model")
        or not isinstance(previous.get("results"), list)
        or not isinstance(retry.get("results"), list)
        or type(previous.get("api_requests")) is not int
        or type(retry.get("api_requests")) is not int
        or not 0 <= previous["api_requests"] <= 30
        or not 0 <= retry["api_requests"] <= 6
    ):
        raise ValueError("Tentativa incompatível com a avaliação anterior.")
    initial: list[dict] = []
    by_key = {}
    for item in previous["results"]:
        if (
            not isinstance(item, dict)
            or type(item.get("scene_number")) is not int
            or not isinstance(item.get("file"), str)
        ):
            raise ValueError("Avaliação anterior inválida.")
        key = (item["scene_number"], item["file"])
        if key in by_key:
            raise ValueError("Cena duplicada na avaliação anterior.")
        by_key[key] = len(initial)
        initial.append(dict(item))
    updated = set()
    for item in retry["results"]:
        if not isinstance(item, dict):
            raise ValueError("Resposta de nova tentativa inválida.")
        key = (item.get("scene_number"), item.get("file"))
        if (
            key not in by_key or key in updated
            or initial[by_key[key]].get("status") != "provider_or_response_failure"
        ):
            raise ValueError("Nova tentativa não corresponde a cena com falha.")
        updated.add(key)
        initial[by_key[key]] = dict(item)
    merged = dict(previous)
    merged["results"] = initial
    merged["attempted"] = len(initial)
    merged["assessed"] = sum(
        item.get("status") == "ai_assessment_for_human_review"
        for item in initial
    )
    merged["api_requests"] = previous["api_requests"] + retry["api_requests"]
    merged["retry_api_requests"] = (
        int(previous.get("retry_api_requests") or 0) + retry["api_requests"]
    )
    merged["human_approved"] = False
    merged["publishing_permitted"] = False
    merged["semantic_content_verified"] = False
    return merged
