"""Opt-in retrieval of independently relevant candidate media for Rick scenes.

Stock providers already exist in MoneyPrinterTurbo. This service queries by
scene *intent*, and imports bounded, provenance-tagged MP4 candidates.
Historical stills come from the existing Commons CC0/public-domain filter.
Nothing here certifies visual accuracy or legal rights; all proposals remain
explicitly reviewable and publishing stays disabled.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import urlsplit

import requests

from app.config import config
from app.models.schema import VideoAspect
from app.services import material
from app.services.rick_auto_commons import download_commons_still, find_commons_stills
from app.services.rick_editorial_assets import import_editorial_material
from app.services.rick_scene_precuration import scene_intent
from app.services.rick_visual_curation import person_anchor

_ALLOWED_VIDEO_HOSTS = frozenset({"videos.pexels.com", "cdn.pixabay.com"})
_MAX_VIDEO = 64 * 1024 * 1024


def _trusted_video_url(url: str) -> bool:
    if not isinstance(url, str) or not 12 <= len(url) <= 2048:
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in _ALLOWED_VIDEO_HOSTS
        and not parsed.username and not parsed.password
        and parsed.port is None
        and parsed.path.lower().endswith(".mp4")
        and not parsed.fragment
    )


def _download_stock_clip(url: str) -> bytes:
    """Bounded HTTPS MP4 transfer; never follow provider/CDN redirects."""
    if not _trusted_video_url(url):
        raise ValueError("Fonte de vídeo fora dos domínios permitidos.")
    try:
        with requests.get(
            url, timeout=(8, 45), stream=True, allow_redirects=False
        ) as response:
            if response.status_code != 200:
                raise ValueError("Fonte de vídeo indisponível ou redirecionada.")
            mime = str(response.headers.get("Content-Type") or "").split(";")[0].lower()
            if mime not in {"video/mp4", "application/octet-stream"}:
                raise ValueError("O provedor não retornou um MP4.")
            size = response.headers.get("Content-Length")
            if size and int(size) > _MAX_VIDEO:
                raise ValueError("Vídeo excede o limite de 64 MB.")
            contents = bytearray()
            for chunk in response.iter_content(chunk_size=256 * 1024):
                contents.extend(chunk)
                if len(contents) > _MAX_VIDEO:
                    raise ValueError("Vídeo excede o limite de 64 MB.")
    except requests.RequestException as exc:
        raise RuntimeError("Falha ao obter vídeo do banco de mídias.") from exc
    data = bytes(contents)
    if len(data) < 16 or data[4:8] != b"ftyp":
        raise ValueError("Fonte retornou um arquivo MP4 inválido.")
    return data


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


def discover_scene_media(
    tasks_root: str | Path,
    task_id: str,
    *,
    subject: str,
    scenes: Sequence[Mapping],
    source_metadata: Mapping[str, Mapping],
    max_stills: int = 8,
    max_clips: int = 8,
) -> dict:
    """Import distinct candidates; never reimport the same provider asset."""
    if (
        not isinstance(scenes, (list, tuple)) or not 1 <= len(scenes) <= 60
        or not isinstance(source_metadata, Mapping)
        or type(max_stills) is not int or not 0 <= max_stills <= 10
        or type(max_clips) is not int or not 0 <= max_clips <= 12
    ):
        raise ValueError("Solicitação de descoberta editorial inválida.")
    existing = {
        str(meta.get("asset_id"))
        for meta in source_metadata.values()
        if isinstance(meta, Mapping) and meta.get("asset_id")
    }
    imported: list[dict] = []
    issues: list[str] = []

    person = person_anchor(subject)
    if person and max_stills:
        try:
            photos = find_commons_stills(person, max_results=max_stills)
        except (RuntimeError, ValueError) as exc:
            issues.append(f"Commons indisponível: {type(exc).__name__}")
            photos = []
        for asset in photos:
            key = f"commons:{asset['source_page']}"
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
    if not provider and max_clips:
        issues.append("Nenhuma chave Pexels/Pixabay configurada para vídeos contextuais.")
    searched: set[str] = set()
    if provider and max_clips:
        for index, scene in enumerate(scenes, 1):
            if len([r for r in imported if r["media_kind"] == "stock_video"]) >= max_clips:
                break
            intent = scene_intent(scene, subject)
            # A generic query like "Gramsci Brazil" can retrieve waterfalls or
            # unrelated scenes. Only search known semantic categories.
            if intent["kind"] in {"general", "historical_person"}:
                continue
            query = intent["query"]
            if query in searched:
                continue
            searched.add(query)
            try:
                candidates = search(query, 3, VideoAspect.portrait) or []
            except (OSError, ValueError, RuntimeError) as exc:
                issues.append(f"Busca {intent['kind']}: {type(exc).__name__}")
                continue
            for candidate in candidates[:12]:
                info = getattr(candidate, "source_info", None)
                if not isinstance(info, dict):
                    continue
                unique = info.get("asset_id")
                page = info.get("source_page")
                key = f"{provider}:{unique}" if unique else ""
                if not key or key in existing or not isinstance(page, str) or not page.startswith("https://"):
                    continue
                url = getattr(candidate, "url", None)
                if not _trusted_video_url(url):
                    continue
                try:
                    data = _download_stock_clip(url)
                    local = import_editorial_material(
                        tasks_root, task_id, "video.mp4", data,
                        scene_number=index,
                        source_note=f"{provider}: {page}"[:350],
                        search_term=query, title=query,
                        asset_id=key[:150],
                    )
                except (ValueError, OSError, RuntimeError) as exc:
                    issues.append(f"Vídeo {intent['kind']}: {type(exc).__name__}")
                    continue
                existing.add(key)
                imported.append({
                    "file": local, "media_kind": "stock_video",
                    "source_page": page,
                    "license_metadata": "não verificada automaticamente",
                })
                break
    return {
        "imported_count": len(imported),
        "imported": imported,
        "searched_intents": sorted(searched),
        "issues": issues[:20],
        "visually_verified": False,
        "rights_verified": False,
    }
