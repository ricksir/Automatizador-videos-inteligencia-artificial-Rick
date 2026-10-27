"""Export and edit Rick scene reviews without calling any online API.

Run from the repo root:
  uv run python scripts/rick_scene_review.py --task-id TASK_ID prepare
  uv run python scripts/rick_scene_review.py --task-id TASK_ID import-photo \
    --scene 1 --file C:\photos\portrait.jpg --source-url https://example.org/... \
    --credit "Museum name" --license "Public domain (check conditions)"
  uv run python scripts/rick_scene_review.py --task-id TASK_ID approve --scene 1
  uv run python scripts/rick_scene_review.py --task-id TASK_ID status

This is a preparation utility, NOT an automatic rendering hook.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import rick_scene_curation as curation  # noqa: E402

MAX_PHOTO_BYTES = 16 * 1024 * 1024
SAFE_TASK_ID = re.compile(r"^[A-Za-z0-9_-]{1,96}$")
ALLOWED_IMAGES = {".jpg", ".jpeg", ".png", ".webp"}


def _get_dir(task_id: str) -> Path:
    if not SAFE_TASK_ID.fullmatch(task_id):
        raise ValueError("Identificador de tarefa inválido")
    base = (ROOT / "storage" / "tasks").resolve()
    dest = (base / task_id).resolve()
    if not dest.is_relative_to(base) or not (dest / "script.json").is_file():
        raise ValueError("A tarefa precisa existir e conter um script.json")
    return dest


def _load_json(filename: Path) -> dict:
    if filename.stat().st_size > 2_000_000:
        raise ValueError("Arquivo de metadados grande demais")
    with filename.open(encoding="utf-8") as inp:
        data = json.load(inp)
    if not isinstance(data, dict):
        raise ValueError("Conteúdo JSON inválido")
    return data


def _write_json(destination: Path, data: dict) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".rick-review-", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=False, indent=2)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, destination)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _load(task_dir: Path, *, create: bool = False):
    script = _load_json(task_dir / "script.json")
    preview = script.get("rick_scene_candidate_preview")
    if not isinstance(preview, dict):
        raise ValueError(
            "A tarefa ainda não possui rick_scene_candidate_preview. "
            "É necessário ter gerado roteiro, áudio e materiais ordenados."
        )
    review_path = task_dir / "rick_scene_review.json"
    if not review_path.is_file():
        if not create:
            raise ValueError("Revisão não criada: execute o comando prepare primeiro")
        review = curation.make_review(preview)
        _write_json(review_path, review)
    else:
        review = _load_json(review_path)
        if review.get("plan_fingerprint") != curation.plan_fingerprint(preview):
            raise ValueError(
                "O roteiro mudou desde o início da revisão. Faça backup da revisão "
                "antiga e gere outra ficha para as novas cenas."
            )
    return script, preview, review, review_path


def _available_names(script: dict, task_dir: Path) -> list[str]:
    names: list[str] = []
    for record in script.get("material_sources", []):
        if isinstance(record, dict) and curation._safe_name(record.get("local_file")):
            names.append(record["local_file"])
    # Locally generated sources are allowed only from the task's own curation folder.
    folder = task_dir / "rick_curated"
    if folder.is_dir():
        names.extend(file.name for file in folder.iterdir()
                     if file.is_file() and not file.is_symlink()
                     and curation._safe_name(file.name))
    return list(dict.fromkeys(names))


def _add_preview_images(task_dir: Path, review: dict) -> dict[str, str]:
    dest = task_dir / "rick_review"
    thumbs = dest / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    thumbnails: dict[str, str] = {}
    if not shutil.which("ffmpeg"):
        return thumbnails
    for entry in review["scenes"]:
        filename = entry.get("file")
        if not curation._safe_name(filename):
            continue
        source = task_dir / "rick_curated" / filename
        if not source.is_file() or source.is_symlink():
            continue
        digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:24]
        destination = thumbs / f"{digest}.jpg"
        if not destination.exists():
            run = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                 "-ss", "0.25", "-i", str(source), "-frames:v", "1",
                 "-vf", "scale=420:-2", "-y", str(destination)],
                capture_output=True, timeout=45, check=False,
            )
            if run.returncode != 0:
                destination.unlink(missing_ok=True)
                continue
        thumbnails[filename] = f"thumbs/{digest}.jpg"
    return thumbnails


def _refresh_html(task_dir: Path, preview: dict, review: dict) -> Path:
    folder = task_dir / "rick_review"
    folder.mkdir(exist_ok=True)
    thumbs = _add_preview_images(task_dir, review)
    output = folder / "storyboard.html"
    output.write_text(curation.render_review_html(preview, review, thumbs),
                      encoding="utf-8")
    return output


def _import_photo(task_dir: Path, args, review: dict) -> str:
    scene = args.scene
    if not isinstance(scene, int) or not 1 <= scene <= len(review["scenes"]):
        raise ValueError("Cena inexistente na revisão")
    image = Path(args.file).expanduser().resolve(strict=True)
    if not image.is_file() or image.is_symlink() or image.suffix.casefold() not in ALLOWED_IMAGES:
        raise ValueError("Escolha uma imagem regular .jpg, .jpeg, .png ou .webp")
    if image.stat().st_size > MAX_PHOTO_BYTES or image.stat().st_size == 0:
        raise ValueError("Imagem vazia ou acima de 16 MiB")
    if not re.fullmatch(r"https?://[^\s<>\"']+", args.source_url, re.I):
        raise ValueError("Informe a página de origem com URL HTTP(S)")
    if not args.credit.strip() or not args.license.strip():
        raise ValueError("Informe autoria/créditos e o status de licença")
    if not 0.5 <= args.duration <= 15:
        raise ValueError("Duração deve estar entre 0,5 e 15 segundos")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg não encontrado no PATH")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()[:16]
    name = f"rick-review-s{scene}-{digest}.mp4"
    folder = task_dir / "rick_curated"
    folder.mkdir(exist_ok=True)
    outfile = folder / name
    temp = folder / f".{name}.partial.mp4"
    if not outfile.exists():
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-loop", "1", "-framerate", "30", "-i", str(image),
            "-t", str(args.duration),
            "-vf", "scale=720:1280:force_original_aspect_ratio=decrease,"
                   "pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p",
            "-an", "-c:v", "libx264", "-preset", "ultrafast",
            "-movflags", "+faststart", str(temp),
        ]
        try:
            p = subprocess.run(command, capture_output=True, timeout=100, check=False)
            if p.returncode or not temp.is_file() or not temp.stat().st_size:
                err = p.stderr.decode("utf-8", "replace")[-800:]
                raise RuntimeError(f"Não foi possível converter a fotografia: {err}")
            os.replace(temp, outfile)
        finally:
            temp.unlink(missing_ok=True)
    entry = review["scenes"][scene - 1]
    entry["approved"] = False  # Imported does NOT mean reviewed/approved
    entry["file"] = name
    entry["source_url"] = args.source_url
    entry["credit"] = args.credit
    entry["license"] = args.license
    entry["editor_note"] = "Fotografia importada e convertida em vídeo local. Verifique a identidade visual."
    return name


def main() -> None:
    parser = argparse.ArgumentParser(description="Rick: curadoria local de cenas")
    parser.add_argument("--task-id", required=True, help="Identificador em storage/tasks")
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("prepare", help="Gerar rick_scene_review.json e storyboard.html")
    commands.add_parser("status", help="Contar aprovações e listar bloqueios")
    approval = commands.add_parser("approve", help="Confirmar manualmente o arquivo de uma cena")
    approval.add_argument("--scene", type=int, required=True)
    approval.add_argument("--file", help="Escolha outro MP4 já registrado no manifesto")
    photo = commands.add_parser("import-photo", help="Converter uma fotografia local em vídeo e selecionar")
    photo.add_argument("--scene", required=True, type=int)
    photo.add_argument("--file", required=True, help="Caminho local da fotografia")
    photo.add_argument("--source-url", required=True, help="Página onde você obteve a imagem")
    photo.add_argument("--credit", required=True, help="Autor/museu/acervo")
    photo.add_argument("--license", required=True, help="Licença ou justificativa de permissão")
    photo.add_argument("--duration", type=float, default=5)
    args = parser.parse_args()

    task_dir = _get_dir(args.task_id)
    script, preview, review, review_path = _load(
        task_dir, create=(args.operation == "prepare"),
    )
    if args.operation == "import-photo":
        filename = _import_photo(task_dir, args, review)
        print("Fotografia convertida:", filename)
        _write_json(review_path, review)
    elif args.operation == "approve":
        if not 1 <= args.scene <= len(review["scenes"]):
            raise ValueError("Número de cena inválido")
        item = review["scenes"][args.scene - 1]
        if args.file is not None:
            if args.file not in _available_names(script, task_dir):
                raise ValueError("Arquivo não registrado entre os materiais disponíveis")
            item["file"] = args.file
        if not item.get("file"):
            raise ValueError("Essa cena ainda não possui material. Importe uma foto antes.")
        item["approved"] = True  # Deliberate, explicit human action
        _write_json(review_path, review)
        print("Aprovação registrada para a cena", args.scene)

    html_file = _refresh_html(task_dir, preview, review)
    report = curation.apply_review(preview, review, _available_names(script, task_dir))
    print(f"Cenas: {len(review['scenes'])}; aprovadas: "
          f"{sum(x.get('approved') is True for x in review['scenes'])}")
    print("Revisão:", review_path)
    print("Storyboard:", html_file)
    print("Status:", report["status"])
    if report["blockers"]:
        print("Pendências:", ", ".join(
            f"cena {issue['scene_number']}: {issue['code']}"
            for issue in report["blockers"]
        ))
    else:
        print("Ficha aprovada por operador. Ela ainda NÃO é enviada ao renderizador.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"ERRO DE REVISÃO: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
