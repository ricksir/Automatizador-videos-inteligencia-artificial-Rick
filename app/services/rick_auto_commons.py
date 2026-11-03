"""Conservative, opt-in Wikimedia Commons image discovery for Rick.

Only HTTPS Wikimedia-owned endpoints, fixed-size responses and public-domain/
CC0 metadata are considered. This is a metadata SCREEN, not confirmation of
identity, historical authenticity or legal rights in every jurisdiction.
Never send API keys or user-provided URLs to the download function.
"""
from __future__ import annotations

import re
import unicodedata
from html import unescape
from pathlib import Path
from urllib.parse import urlsplit

import requests

from app.services.rick_editorial_assets import _validate_upload

_API = "https://commons.wikimedia.org/w/api.php"
_USER_AGENT = (
    "RickAutoCommons/0.1 "
    "(https://github.com/ricksir/Automatizador-videos-inteligencia-artificial-Rick)"
)
_MAX_IMAGE = 12 * 1024 * 1024
_ALLOWED_MIME = {"image/jpeg": ".jpg", "image/png": ".png"}


def _normalized(value: str) -> str:
    chars = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(re.findall(r"[a-z0-9]+", "".join(
        char for char in chars if not unicodedata.combining(char)
    )))


def _metadata_value(values: dict, key: str) -> str:
    entry = values.get(key)
    if not isinstance(entry, dict):
        return ""
    value = entry.get("value")
    return str(value).strip() if isinstance(value, (str, bool)) else ""


def _trusted_url(url: str, *, media: bool) -> bool:
    if not isinstance(url, str) or len(url) > 1800:
        return False
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or parsed.port is not None or parsed.query or parsed.fragment):
            return False
    except ValueError:
        return False
    if media:
        return parsed.hostname in {"upload.wikimedia.org", "thumb.wikimedia.org"} and (
            parsed.path.startswith("/wikipedia/commons/")
        )
    return parsed.hostname == "commons.wikimedia.org" and parsed.path.startswith("/wiki/File:")


def _eligible_image(page: dict, subject: str) -> dict | None:
    """Accept only filenames naming the subject and a strictly screened license."""
    if not isinstance(page, dict) or page.get("ns") != 6:
        return None
    title = page.get("title")
    if not isinstance(title, str) or not title.startswith("File:"):
        return None
    if not (3 <= len(subject) <= 100 and _normalized(subject) in _normalized(title)):
        return None
    if Path(title).suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        return None
    infos = page.get("imageinfo")
    if not isinstance(infos, list) or len(infos) != 1:
        return None
    info = infos[0]
    if not isinstance(info, dict) or info.get("mime") not in _ALLOWED_MIME:
        return None
    meta = info.get("extmetadata")
    if not isinstance(meta, dict):
        return None
    license_name = _metadata_value(meta, "LicenseShortName")
    license_key = license_name.casefold()
    copyrighted = _metadata_value(meta, "Copyrighted").casefold()
    nonfree = _metadata_value(meta, "NonFree").casefold()
    restrictions = _metadata_value(meta, "Restrictions")
    if nonfree in {"true", "1"} or restrictions:
        return None
    if license_key in {"cc0", "cc0 1.0"}:
        license_url = _metadata_value(meta, "LicenseUrl")
        if not license_url.startswith("https://creativecommons.org/publicdomain/zero/1.0"):
            return None
    elif license_key == "public domain" and copyrighted in {"false", "0"}:
        pass
    else:
        return None
    direct = info.get("thumburl") or info.get("url")
    page_url = info.get("descriptionurl")
    if not _trusted_url(direct, media=True) or not _trusted_url(page_url, media=False):
        return None
    return {
        "title": title,
        "image_url": direct,
        "source_page": page_url,
        "license": license_name,
        "author_metadata": re.sub(
            r"<[^>]*>", "", unescape(_metadata_value(meta, "Artist"))
        )[:160],
        "mime": info["mime"],
        "selection_basis": "filename_subject_match_only",
        "identity_verified": False,
        "license_legally_verified": False,
    }


def find_commons_stills(subject: str, *, max_results: int = 6) -> list[dict]:
    """Return a bounded list; do not accept URLs from the caller."""
    if (not isinstance(subject, str) or not 3 <= len(subject.strip()) <= 80
            or not 1 <= max_results <= 10):
        raise ValueError("Assunto histórico inválido para pesquisa automática.")
    name = " ".join(subject.split())
    if not re.fullmatch(r"[\wÀ-ÿ .'-]{3,80}", name):
        raise ValueError("Caracteres inválidos no assunto histórico.")
    params = {
        "action": "query", "generator": "search", "gsrsearch": name,
        "gsrnamespace": "6", "gsrlimit": "24", "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata", "iiurlwidth": "900",
        "format": "json", "formatversion": "2",
    }
    try:
        response = requests.get(
            _API, params=params, timeout=(6, 20), allow_redirects=False,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        )
        response.raise_for_status()
        if response.status_code != 200 or len(response.content) > 2_000_000:
            raise ValueError("Resposta excessiva ou inválida do Commons.")
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError("A pesquisa no Wikimedia Commons falhou.") from exc
    pages = data.get("query", {}).get("pages", []) if isinstance(data, dict) else []
    if not isinstance(pages, list):
        return []
    found = []
    seen_urls = set()
    for page in sorted(pages[:24], key=lambda p: p.get("index", 1000) if isinstance(p, dict) else 1000):
        item = _eligible_image(page, name)
        if item and item["source_page"] not in seen_urls:
            seen_urls.add(item["source_page"])
            found.append(item)
            if len(found) >= max_results:
                break
    return found


def download_commons_still(asset: dict) -> tuple[str, bytes]:
    """Download only the previously validated Wikimedia-hosted image URL."""
    if not isinstance(asset, dict):
        raise ValueError("Registro de mídia inválido.")
    url = asset.get("image_url")
    mime = asset.get("mime")
    if not _trusted_url(url, media=True) or mime not in _ALLOWED_MIME:
        raise ValueError("URL externa ou tipo de imagem não autorizado.")
    try:
        with requests.get(
            url, stream=True, timeout=(6, 25), allow_redirects=False,
            headers={"User-Agent": _USER_AGENT},
        ) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError("Redirecionamento de imagem bloqueado.")
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type != mime:
                raise ValueError("Tipo MIME não corresponde ao arquivo.")
            size = response.headers.get("Content-Length")
            if size is not None and int(size) > _MAX_IMAGE:
                raise ValueError("Imagem do Commons excede o limite.")
            buffer = bytearray()
            for chunk in response.iter_content(chunk_size=256 * 1024):
                buffer.extend(chunk)
                if len(buffer) > _MAX_IMAGE:
                    raise ValueError("Imagem do Commons excede 12 MB.")
    except requests.RequestException as exc:
        raise RuntimeError("Falha no download de imagem do Commons.") from exc
    extension = _ALLOWED_MIME[mime]
    name = "commons-photo" + extension
    _validate_upload(name, bytes(buffer))
    return name, bytes(buffer)
