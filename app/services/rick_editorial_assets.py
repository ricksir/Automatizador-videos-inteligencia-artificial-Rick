"""Local-only, opt-in visual materials for Rick's human editorial review.

Uploads never amend script.json or cached stock media. Photos are converted into
silent, vertical MP4 clips with the already-installed local FFmpeg executable.
A valid file, filename or source description is NOT visual or licence approval.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from app.services.rick_editorial_workspace import task_folder

_CATALOG = "rick_editorial_materials.json"
_FOLDER = "rick_editorial_assets"
_NAME = re.compile(r"rick-local-[0-9a-f]{32}\.mp4\Z")
_MAX_VIDEO = 64 * 1024 * 1024
_MAX_IMAGE = 12 * 1024 * 1024
_MAX_ASSETS = 80


def _directory(folder: Path, *, create: bool = False) -> Path:
    assets = folder / _FOLDER
    if assets.is_symlink():
        raise ValueError("Pasta de mídias editoriais não autorizada.")
    if create:
        assets.mkdir(exist_ok=True)
    if assets.exists() and (not assets.is_dir() or assets.resolve().parent != folder.resolve()):
        raise ValueError("Pasta de mídias editoriais inválida.")
    return assets


def _entries(folder: Path) -> list[dict]:
    catalog = folder / _CATALOG
    if catalog.is_symlink():
        raise ValueError("Catálogo de mídias editoriais não autorizado.")
    if not catalog.exists():
        return []
    if not catalog.is_file() or catalog.stat().st_size > 80_000:
        raise ValueError("Catálogo de mídias editoriais inválido.")
    try:
        data = json.loads(catalog.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Não foi possível validar o catálogo editorial.") from exc
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("materials"), list):
        raise ValueError("Catálogo de mídias editoriais inválido.")
    entries = data["materials"]
    if len(entries) > _MAX_ASSETS or any(not isinstance(item, dict) for item in entries):
        raise ValueError("Quantidade ou registros de mídia inválidos.")
    return entries


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as src:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_editorial_assets(tasks_root: str | Path, task_id: str) -> tuple[dict[str, str], dict[str, dict]]:
    """Return only recorded, intact, task-owned regular MP4s. Never scan folders."""
    folder = task_folder(tasks_root, task_id)
    records = _entries(folder)
    assets = _directory(folder)
    paths: dict[str, str] = {}
    metadata: dict[str, dict] = {}
    for record in records:
        name = record.get("local_file")
        digest = record.get("sha256")
        if (not isinstance(name, str) or not _NAME.fullmatch(name)
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or name in paths):
            raise ValueError("Registro de material editorial inválido ou duplicado.")
        candidate = assets / name
        if (not candidate.is_file() or candidate.is_symlink()
                or candidate.resolve().parent != assets.resolve()
                or not 0 < candidate.stat().st_size <= _MAX_VIDEO
                or _file_digest(candidate) != digest):
            # A missing/altered file must never remain eligible for approval or export.
            continue
        paths[name] = str(candidate.resolve())
        metadata[name] = {
            "provider": "Importação local (não verificada)",
            "source_page": str(record.get("source_page") or "")[:350],
            "search_term": f"Adicionado para cena {record.get('scene_number')}",
            "asset_id": name,
        }
    return paths, metadata


def _validate_upload(upload_name: str, data: bytes) -> str:
    if not isinstance(upload_name, str) or not upload_name or "/" in upload_name or "\\" in upload_name:
        raise ValueError("Nome de arquivo de mídia inválido.")
    if not isinstance(data, bytes):
        raise ValueError("Conteúdo da mídia inválido.")
    ext = Path(upload_name).suffix.casefold()
    if ext == ".mp4":
        if not 16 <= len(data) <= _MAX_VIDEO or data[4:8] != b"ftyp":
            raise ValueError("Arquivo MP4 inválido ou acima do limite de 64 MB.")
    elif ext in (".jpg", ".jpeg", ".png"):
        if not 16 <= len(data) <= _MAX_IMAGE:
            raise ValueError("Imagem inválida ou acima do limite de 12 MB.")
        from PIL import Image, UnidentifiedImageError

        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ("JPEG", "PNG"):
                    raise ValueError("Somente imagens JPEG/PNG são aceitas.")
                width, height = image.size
                if not 0 < width * height <= 20_000_000:
                    raise ValueError("Imagem excede o limite de 20 megapixels.")
                image.verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("Não foi possível validar a imagem.") from exc
    else:
        raise ValueError("Formato não suportado. Envie MP4, JPG ou PNG.")
    return ext


def _image_to_video(image: Path, output: Path) -> None:
    """Use the packaged local FFmpeg; never download or fetch stock assets."""
    from imageio_ffmpeg import get_ffmpeg_exe

    try:
        subprocess.run(
            [
                get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
                "-nostdin", "-y", "-loop", "1", "-framerate", "24",
                "-i", str(image), "-t", "4", "-vf",
                "scale=720:1280:force_original_aspect_ratio=decrease,"
                "pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1",
                "-an", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                "-f", "mp4", str(output),
            ],
            check=True, timeout=90, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("Falha na conversão local de imagem em vídeo.") from exc
    if not output.is_file() or not 0 < output.stat().st_size <= _MAX_VIDEO:
        raise ValueError("Conversão da imagem não produziu MP4 válido.")


def import_editorial_material(
    tasks_root: str | Path, task_id: str, upload_name: str, data: bytes,
    *, scene_number: int, source_note: str,
) -> str:
    """Add one task-owned file after explicit upload. No approval is created."""
    folder = task_folder(tasks_root, task_id)
    ext = _validate_upload(upload_name, data)
    if type(scene_number) is not int or not 1 <= scene_number <= 60:
        raise ValueError("Número de cena inválido.")
    if not isinstance(source_note, str) or not source_note.strip() or len(source_note) > 350:
        raise ValueError("Informe a origem e a condição de uso da mídia.")
    records = _entries(folder)
    if len(records) >= _MAX_ASSETS:
        raise ValueError("Limite de 80 mídias editoriais atingido.")
    assets = _directory(folder, create=True)
    name = f"rick-local-{uuid4().hex}.mp4"
    output = assets / name
    temporary_image = None
    try:
        if ext == ".mp4":
            with output.open("xb") as dest:
                dest.write(data)
        else:
            with tempfile.NamedTemporaryFile(
                dir=assets, suffix=ext, prefix=".rick-image-",
                delete=False,
            ) as source:
                source.write(data)
                temporary_image = Path(source.name)
            _image_to_video(temporary_image, output)
        digest = _file_digest(output)
        records.append({
            "local_file": name,
            "sha256": digest,
            "scene_number": scene_number,
            "source_page": source_note.strip(),
            "kind": "video" if ext == ".mp4" else "image_converted_locally",
        })
        temporary_catalog = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=folder, prefix=".rick-materials-", suffix=".tmp",
                mode="w", encoding="utf-8", delete=False,
            ) as file:
                temporary_catalog = Path(file.name)
                json.dump({"version": 1, "materials": records}, file, ensure_ascii=False, indent=2)
            os.replace(temporary_catalog, folder / _CATALOG)
            temporary_catalog = None
        finally:
            if temporary_catalog is not None:
                temporary_catalog.unlink(missing_ok=True)
        return name
    except Exception:
        output.unlink(missing_ok=True)
        raise
    finally:
        if temporary_image is not None:
            temporary_image.unlink(missing_ok=True)

_EXCLUSIONS = "rick_editorial_exclusions.json"
_SAFE_VIDEO_NAME = re.compile(r"[A-Za-z0-9._-]{1,180}\\.(?:mp4|mov|mkv|avi|webm)\\Z", re.IGNORECASE)


def excluded_editorial_materials(tasks_root: str | Path, task_id: str) -> set[str]:
    """Task-wide manual rejection; absent names cannot silently reappear."""
    folder = task_folder(tasks_root, task_id)
    source = folder / _EXCLUSIONS
    if source.is_symlink():
        raise ValueError("Lista de exclusões de mídias não autorizada.")
    if not source.exists():
        return set()
    if not source.is_file() or source.stat().st_size > 40_000:
        raise ValueError("Lista de exclusões de mídias inválida.")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Não foi possível ler as mídias descartadas.") from exc
    names = data.get("filenames") if isinstance(data, dict) and data.get("version") == 1 else None
    if not isinstance(names, list) or len(names) > 250 or any(
        not isinstance(name, str) or not _SAFE_VIDEO_NAME.fullmatch(name) for name in names
    ):
        raise ValueError("Lista de exclusões de mídias inválida.")
    return set(names)


def exclude_editorial_material(tasks_root: str | Path, task_id: str, name: str) -> None:
    """Hide a human-rejected basename throughout this task without deleting media."""
    folder = task_folder(tasks_root, task_id)
    if not isinstance(name, str) or not _SAFE_VIDEO_NAME.fullmatch(name):
        raise ValueError("Nome de mídia inválido.")
    excluded = excluded_editorial_materials(tasks_root, task_id)
    excluded.add(name)
    if len(excluded) > 250:
        raise ValueError("Limite de exclusões atingido.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, dir=folder,
            prefix=".rick-exclusions-", suffix=".tmp",
        ) as dest:
            temporary = Path(dest.name)
            json.dump(
                {"version": 1, "filenames": sorted(excluded)}, dest,
                ensure_ascii=False, indent=2,
            )
        os.replace(temporary, folder / _EXCLUSIONS)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def restore_editorial_material(tasks_root: str | Path, task_id: str, name: str) -> None:
    """Allow an explicit human undo of a task-wide clip rejection."""
    if not isinstance(name, str) or not _SAFE_VIDEO_NAME.fullmatch(name):
        raise ValueError("Nome de mídia inválido.")
    excluded = excluded_editorial_materials(tasks_root, task_id)
    if name not in excluded:
        return
    excluded.remove(name)
    folder = task_folder(tasks_root, task_id)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, dir=folder,
            prefix=".rick-exclusions-", suffix=".tmp",
        ) as dest:
            temporary = Path(dest.name)
            json.dump(
                {"version": 1, "filenames": sorted(excluded)}, dest,
                ensure_ascii=False, indent=2,
            )
        os.replace(temporary, folder / _EXCLUSIONS)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
