"""Opt-in retrieval of independently relevant candidate media for Rick scenes.

Stock providers already exist in MoneyPrinterTurbo. This service queries by
scene *intent*, and imports bounded, provenance-tagged MP4 candidates.
Historical stills come from the existing Commons CC0/public-domain filter.
Nothing here certifies visual accuracy or legal rights; all proposals remain
explicitly reviewable and publishing stays disabled.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

from app.config import config
from app.models.schema import VideoAspect
from app.services import material
from app.services.rick_auto_commons import download_commons_still, find_commons_stills
from app.services.rick_editorial_assets import import_editorial_material
from app.services.rick_scene_precuration import scene_search_context
from app.services.rick_visual_curation import person_anchor

_ALLOWED_VIDEO_HOSTS = frozenset({"videos.pexels.com", "cdn.pixabay.com"})
_MAX_VIDEO = 64 * 1024 * 1024


def _trusted_video_url(url: str) -> bool:
    if not isinstance(url, str) or not 12 <= len(url) <= 2048:
        return False
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in _ALLOWED_VIDEO_HOSTS
        and not parsed.username and not parsed.password
        and port is None
        and parsed.path.lower().endswith(".mp4")
        and not parsed.fragment
    )



def _candidate_download_variants(candidate: object) -> list[str]:
    """Primary URL plus up to four *verified-host* smaller editorial options."""
    original = getattr(candidate, "url", None)
    if not _trusted_video_url(original):
        return []
    urls = [original]
    info = getattr(candidate, "source_info", None)
    if not isinstance(info, dict):
        return urls
    alternatives = info.get("editorial_rendition_alternatives")
    if not isinstance(alternatives, list):
        return urls
    for variant in alternatives[:8]:
        if not isinstance(variant, dict):
            continue
        url = variant.get("url")
        if not _trusted_video_url(url) or url in urls:
            continue
        try:
            w = int(variant["width"])
            h = int(variant["height"])
            size = variant.get("size_bytes")
            size = int(size) if size is not None else None
        except (TypeError, ValueError, KeyError, OverflowError):
            continue
        if (w < 360 or h < 640 or h <= w
                or (size is not None and (size <= 0 or size > _MAX_VIDEO))):
            continue
        urls.append(url)
        if len(urls) >= 5:
            break
    return urls


class StockDownloadError(ValueError):
    """Stable, credential-free cause for a rejected stock clip."""

    def __init__(self, code: str, *, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(code)


def _download_stock_clip(url: str) -> bytes:
    """Bounded HTTPS MP4 transfer; retry transient errors on the *same* URL.

    Invalid bytes, permissions, and format failures are final. Never issue a
    new paid-generation request and never follow redirects or arbitrary URLs.
    """
    if not _trusted_video_url(url):
        raise StockDownloadError("source_host_not_allowed")
    for attempt in range(3):
        try:
            with requests.get(
                url, timeout=(8, 45), stream=True, allow_redirects=False
            ) as response:
                status = response.status_code
                if status != 200:
                    if status == 429:
                        raise StockDownloadError("http_rate_limited", retryable=True)
                    if status in (500, 502, 503, 504):
                        raise StockDownloadError("http_server_error", retryable=True)
                    if status in (301, 302, 303, 307, 308):
                        raise StockDownloadError("http_redirect_disallowed")
                    if status in (401, 403):
                        raise StockDownloadError("http_access_denied")
                    if status == 404:
                        raise StockDownloadError("http_not_found")
                    raise StockDownloadError("http_response_rejected")
                mime = str(response.headers.get("Content-Type") or "").split(";")[0].lower()
                if mime not in {"video/mp4", "application/octet-stream"}:
                    raise StockDownloadError("unexpected_content_type")
                length = response.headers.get("Content-Length")
                if length:
                    try:
                        size = int(length)
                    except (TypeError, ValueError) as exc:
                        raise StockDownloadError("invalid_content_length") from exc
                    if size > _MAX_VIDEO or size < 0:
                        raise StockDownloadError("video_too_large")
                contents = bytearray()
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    contents.extend(chunk)
                    if len(contents) > _MAX_VIDEO:
                        raise StockDownloadError("video_too_large")
            data = bytes(contents)
            if len(data) < 16 or data[4:8] != b"ftyp":
                raise StockDownloadError("invalid_mp4_header")
            return data
        except StockDownloadError as exc:
            if not exc.retryable or attempt == 2:
                raise
        except requests.Timeout as exc:
            if attempt == 2:
                raise StockDownloadError("download_timeout", retryable=True) from exc
        except requests.RequestException as exc:
            if attempt == 2:
                raise StockDownloadError("download_network_error", retryable=True) from exc
        time.sleep(0.2 * (attempt + 1))
    raise StockDownloadError("download_retry_exhausted", retryable=True)


def _failure_code(error: Exception, stage: str) -> str:
    """Only permit finite, public diagnostic labels; never stringify URLs/keys."""
    if isinstance(error, StockDownloadError):
        return error.code
    if stage == "import":
        message = str(error).casefold()
        if "limite de 80 mídias" in message:
            return "catalog_capacity_reached"
        if "arquivo mp4 inválido" in message:
            return "invalid_mp4_import"
        if "conversão" in message or "ffmpeg" in message:
            return "ffmpeg_conversion_failed"
        if "catálogo" in message or "registro" in message:
            return "editorial_catalog_invalid"
        return "editorial_import_failed"
    if isinstance(error, requests.Timeout):
        return "search_timeout"
    if isinstance(error, requests.RequestException):
        return "search_network_error"
    return "search_provider_exception"


def _failure_record(
    scene_number: int, kind: str, provider: str, stage: str, error: Exception,
) -> dict:
    """Public diagnostic record with no URL, API key or exception message."""
    return {
        "scene": scene_number,
        "intent": kind,
        "provider": provider,
        "stage": stage,
        "code": _failure_code(error, stage),
        "exception_type": type(error).__name__[:55],
        "retryable": (
            bool(getattr(error, "retryable", False)) if stage == "download"
            else isinstance(error, (requests.Timeout, requests.ConnectionError))
        ),
    }


def _stock_provider() -> tuple[str | None, object | None]:
    """Select the first stock source with credentials already configured."""
    # Do not log, serialize or return API keys. Pexels/Pixabay searches use
    # the existing provider integrations and their own authentication.
    for provider, setting, fetch in (
        ("pexels", "pexels_api_keys", material.search_videos_pexels),
        ("pixabay", "pixabay_api_keys", material.search_videos_pixabay),
    ):
        value = config.app.get(setting)
        if isinstance(value, str) and value.strip():
            return provider, fetch
        if isinstance(value, (list, tuple)) and any(
            isinstance(entry, str) and entry.strip() for entry in value
        ):
            return provider, fetch
    return None, None



_ALTERNATE_SEARCHES = {
    "elections": ("voting ballot", "polling station"),
    "institutions": ("parliament interior", "government chamber"),
    "demonstrations": ("peaceful protest crowd", "public demonstration"),
    "documents": ("old newspaper archives", "historical manuscript"),
    "education": ("students university library", "people studying books"),
    "ideas": ("people debating ideas", "group discussion books"),
}


def _secondary_stock_provider(primary: str) -> tuple[str | None, object | None]:
    """Use an independently configured free stock catalog as fallback."""
    options = (
        ("pexels", "pexels_api_keys", material.search_videos_pexels),
        ("pixabay", "pixabay_api_keys", material.search_videos_pixabay),
    )
    for provider, setting, fetch in options:
        if provider == primary:
            continue
        value = config.app.get(setting)
        if (isinstance(value, str) and value.strip()) or (
            isinstance(value, (list, tuple)) and any(
                isinstance(key, str) and key.strip() for key in value
            )
        ):
            return provider, fetch
    return None, None


def discover_scene_media(
    tasks_root: str | Path,
    task_id: str,
    *,
    subject: str,
    scenes: Sequence[Mapping],
    source_metadata: Mapping[str, Mapping],
    max_stills: int = 8,
    max_clips: int = 8,
    priority_scene_numbers: Sequence[int] | None = None,
    search_variants: bool = False,
) -> dict:
    """Import distinct candidates; never reimport the same provider asset."""
    if (
        not isinstance(scenes, (list, tuple)) or not 1 <= len(scenes) <= 60
        or not isinstance(source_metadata, Mapping)
        or type(max_stills) is not int or not 0 <= max_stills <= 10
        or type(max_clips) is not int or not 0 <= max_clips <= 12
        or type(search_variants) is not bool
    ):
        raise ValueError("Solicitação de descoberta editorial inválida.")
    if priority_scene_numbers is not None and (
        not isinstance(priority_scene_numbers, (list, tuple))
        or len(priority_scene_numbers) > len(scenes)
        or any(type(i) is not int or i < 1 or i > len(scenes)
               for i in priority_scene_numbers)
    ):
        raise ValueError("Lista de cenas prioritárias inválida.")
    priority = list(dict.fromkeys(priority_scene_numbers or []))
    ordered = priority + [
        idx for idx in range(1, len(scenes) + 1) if idx not in priority
    ]
    existing = {
        str(meta.get("asset_id"))
        for meta in source_metadata.values()
        if isinstance(meta, Mapping) and meta.get("asset_id")
    }
    imported: list[dict] = []
    issues: list[str] = []
    diagnostics: list[dict] = []

    person = person_anchor(subject)
    if person and max_stills:
        try:
            photos = find_commons_stills(person, max_results=max_stills)
        except (RuntimeError, ValueError) as exc:
            issues.append(f"Commons indisponível: {type(exc).__name__}")
            photos = []
        for asset in photos:
            key = "commons:" + sha256(asset["source_page"].encode("utf-8")).hexdigest()[:40]
            if key in existing:
                continue
            try:
                name, data = download_commons_still(asset)
                file = import_editorial_material(
                    tasks_root, task_id, name, data, scene_number=1,
                    source_note=f"Commons {asset['source_page']} | {asset['license']}"[:350],
                    search_term=f"{person} portrait photograph",
                    title=asset["title"][:150], asset_id=key[:150],
                )
            except (ValueError, OSError, RuntimeError) as exc:
                issues.append(f"Foto não importada: {type(exc).__name__}")
                continue
            existing.add(key)
            imported.append({
                "file": file, "media_kind": "historical_still",
                "source_page": asset["source_page"],
                "license_metadata": asset["license"],
            })

    provider, search = _stock_provider()
    fallback_provider, fallback_search = (
        _secondary_stock_provider(provider) if search_variants and provider
        else (None, None)
    )
    if not provider and max_clips:
        issues.append("Nenhuma chave Pexels/Pixabay configurada para vídeos contextuais.")
    searched: set[str] = set()
    attempted: set[tuple[str, str]] = set()
    attempted_count = 0
    skipped = {"duplicate": 0, "invalid_source": 0, "download_failed": 0}
    lower_rendition_selected = 0
    oversized_primary_recovered = 0
    if provider and max_clips:
        imported_stock = 0
        for index in ordered:
            if imported_stock >= max_clips or attempted_count >= 16:
                break
            intent = scene_search_context(scenes, index - 1, subject)
            if intent["kind"] in {"general", "historical_person"}:
                continue
            searches = [intent["query"]]
            if search_variants:
                searches.extend(_ALTERNATE_SEARCHES.get(intent["kind"], ()))
            sources = [(provider, search)]
            if fallback_provider and fallback_search:
                sources.append((fallback_provider, fallback_search))
            imported_for_scene = 0
            # Search alternate wording or another configured provider when
            # the first search yields no usable licensed-media candidate.
            for query in searches:
                if imported_for_scene >= 2 or imported_stock >= max_clips:
                    break
                for active_provider, active_search in sources:
                    if (imported_for_scene >= 2 or imported_stock >= max_clips
                            or attempted_count >= 16):
                        break
                    dedupe = (active_provider, query)
                    if dedupe in attempted:
                        continue
                    attempted.add(dedupe)
                    searched.add(query)
                    attempted_count += 1
                    try:
                        candidates = active_search(query, 3, VideoAspect.portrait) or []
                    except (OSError, ValueError, RuntimeError, requests.RequestException) as exc:
                        record = _failure_record(
                            index, intent["kind"], active_provider, "search", exc,
                        )
                        diagnostics.append(record)
                        issues.append(
                            f"Busca {intent['kind']} ({active_provider}): "
                            f"etapa={record['stage']}, causa={record['code']}"
                        )
                        continue
                    if not isinstance(candidates, (list, tuple)):
                        record = _failure_record(
                            index, intent["kind"], active_provider, "search",
                            TypeError("unexpected results type"),
                        )
                        diagnostics.append(record)
                        issues.append(
                            f"Busca {intent['kind']} ({active_provider}): "
                            "etapa=search, causa=search_provider_exception"
                        )
                        continue
                    for candidate in candidates[:12]:
                        if imported_stock >= max_clips or imported_for_scene >= 2:
                            break
                        info = getattr(candidate, "source_info", None)
                        if not isinstance(info, dict):
                            skipped["invalid_source"] += 1
                            continue
                        unique = info.get("asset_id")
                        page = info.get("source_page")
                        key = f"{active_provider}:{unique}" if unique else ""
                        if key in existing:
                            skipped["duplicate"] += 1
                            continue
                        if (not key or not isinstance(page, str)
                                or not page.startswith("https://")):
                            skipped["invalid_source"] += 1
                            continue
                        urls = _candidate_download_variants(candidate)
                        if not urls:
                            skipped["invalid_source"] += 1
                            continue
                        data = None
                        had_oversized_primary = False
                        chosen_rendition = 0
                        for rendition_index, rendition_url in enumerate(urls):
                            try:
                                data = _download_stock_clip(rendition_url)
                                chosen_rendition = rendition_index
                                break
                            except (ValueError, OSError, RuntimeError, requests.RequestException) as exc:
                                # Oversize is a *per-rendition* failure, not a
                                # reason to discard the whole provider asset.
                                # Retry the next lower-size provider URL only
                                # when it is separately listed and vetted.
                                if (isinstance(exc, StockDownloadError)
                                        and exc.code == "video_too_large"
                                        and rendition_index + 1 < len(urls)):
                                    had_oversized_primary = (
                                        had_oversized_primary or rendition_index == 0
                                    )
                                    continue
                                skipped["download_failed"] += 1
                                record = _failure_record(
                                    index, intent["kind"], active_provider,
                                    "download", exc,
                                )
                                diagnostics.append(record)
                                issues.append(
                                    f"Vídeo {intent['kind']} ({active_provider}): "
                                    f"etapa=download, causa={record['code']}"
                                )
                                break
                        if data is None:
                            continue
                        try:
                            local = import_editorial_material(
                                tasks_root, task_id, "video.mp4", data,
                                scene_number=index,
                                source_note=f"{active_provider}: {page}"[:350],
                                search_term=query, title=query,
                                asset_id=key[:150],
                            )
                        except (ValueError, OSError, RuntimeError) as exc:
                            skipped["download_failed"] += 1
                            record = _failure_record(
                                index, intent["kind"], active_provider, "import", exc,
                            )
                            diagnostics.append(record)
                            issues.append(
                                f"Vídeo {intent['kind']} ({active_provider}): "
                                f"etapa=import, causa={record['code']}"
                            )
                            continue
                        if chosen_rendition:
                            lower_rendition_selected += 1
                            if had_oversized_primary:
                                oversized_primary_recovered += 1
                        existing.add(key)
                        imported.append({
                            "file": local, "media_kind": "stock_video",
                            "source_page": page,
                            "license_metadata": "não verificada automaticamente",
                        })
                        imported_stock += 1
                        imported_for_scene += 1
    return {
        "imported_count": len(imported),
        "imported": imported,
        "searched_intents": sorted(searched),
        "search_requests": attempted_count,
        "skipped_candidates": skipped,
        "smaller_renditions_used": lower_rendition_selected,
        "oversized_primaries_recovered": oversized_primary_recovered,
        "diagnostics": diagnostics[:40],
        "failure_count": len(diagnostics),
        "priority_scene_numbers": priority,
        "issues": issues[:20],
        "visually_verified": False,
        "rights_verified": False,
    }
