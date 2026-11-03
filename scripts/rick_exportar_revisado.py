"""Explicit, offline export of a completely reviewed video.

Example on Windows:
    uv run python scripts/rick_exportar_revisado.py --task-id 15241f2a-e3d --confirm

Dry run checks approvals, source files, audio and scene times without encoding.
No LLM/TTS, stock download, background-music API or publication is called.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.rick_review_render import (  # noqa: E402
    export_reviewed_video,
    prepare_reviewed_export,
)
from app.utils import utils  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rick: exportar montagem humana revisada")
    parser.add_argument("--task-id", required=True, help="ID completo da tarefa exibido no painel")
    parser.add_argument(
        "--confirm", action="store_true",
        help="Autorizar geração de novo MP4 (sem API e sem alterar o vídeo original)",
    )
    parser.add_argument(
        "--sem-legendas", action="store_true",
        help="Permitir exportação sem legenda quando subtitle.srt não existe",
    )
    args = parser.parse_args(argv)
    root = utils.storage_dir("tasks")
    cache = utils.storage_dir("cache_videos")
    try:
        preflight = prepare_reviewed_export(
            root, args.task_id, cache_dir=cache, without_subtitles=args.sem_legendas,
        )
        print(
            f"Preflight aprovado: {preflight['scene_count']} cenas, "
            f"{len(preflight['timeline']['segments'])} segmentos, "
            f"{preflight['duration']:.2f}s de áudio original."
        )
        if not args.confirm:
            print("Modo de análise apenas. Use --confirm para criar o MP4 revisado.")
            return 0
        output = export_reviewed_video(
            root, args.task_id, cache_dir=cache, without_subtitles=args.sem_legendas,
        )
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Exportação bloqueada: {exc}", file=sys.stderr)
        return 1
    print(f"MP4 REVISADO: {output['output']}")
    print(f"Relatório local: {output['report']}")
    print("O MP4 original e o relatório de revisão humana não foram alterados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
