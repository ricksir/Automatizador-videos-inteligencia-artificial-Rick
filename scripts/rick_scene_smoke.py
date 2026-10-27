"""Rick: offline end-to-end MP4 smoke test for the experimental scene renderer.

Creates two synthetic stock clips (red and green), a 4-second test tone
instead of paid TTS, and a simple two-scene timeline. It runs the REAL
MoviePy/FFmpeg combining and final audio muxing functions, then checks
video timing, audio presence, dimensions and color order with ffprobe.

Run from the repository root on Windows:
    uv run python scripts/rick_scene_smoke.py

No API keys, stock-footage requests, model calls or publication. Outputs are
kept under storage/rick_smoke/ (gitignored) for manual playback and review.
This verifies technical scene sequencing, not subject relevance or speech
alignment. In particular, the tone is NOT a human narration.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models.schema import (  # noqa: E402
    VideoAspect,
    VideoConcatMode,
    VideoFitMode,
    VideoParams,
)
from app.services import video  # noqa: E402
from app.services.rick_scene_timeline import (  # noqa: E402
    build_scene_render_preflight,
)

OUTPUT_DIR = ROOT / "storage" / "rick_smoke"
AUDIO_DURATION = 4.0
SOURCE_SECONDS = 2.7


def _execute(command: list[str], *, binary: bool = False) -> bytes | str:
    """Run a local executable; fail with a short actionable error."""
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode:
        diagnostic = result.stderr.decode("utf-8", "replace")[-2400:]
        raise RuntimeError(
            f"Falha ao executar {Path(command[0]).name} "
            f"(código {result.returncode}):\n{diagnostic}"
        )
    if binary:
        return result.stdout
    return result.stdout.decode("utf-8", "replace")


def _ffmpeg(*arguments: str) -> None:
    _execute(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *arguments]
    )


def _probe(filename: Path) -> dict:
    return json.loads(
        str(
            _execute(
                [
                    "ffprobe", "-v", "error", "-show_format", "-show_streams",
                    "-of", "json", str(filename),
                ]
            )
        )
    )


def _pixel(filename: Path, second: float) -> tuple[int, int, int]:
    """Extract an average RGB pixel: enough to distinguish plain color clips."""
    raw = _execute(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-ss", str(second), "-i", str(filename),
            "-frames:v", "1", "-vf", "scale=1:1:flags=area",
            "-c:v", "rawvideo", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
        ],
        binary=True,
    )
    if not isinstance(raw, bytes) or len(raw) != 3:
        raise RuntimeError("Não foi possível ler um quadro RGB do vídeo")
    return tuple(raw)


def _media_file(color: str, destination: Path) -> None:
    _ffmpeg(
        "-f", "lavfi",
        "-i", f"color=c={color}:s=540x960:r=30:d={SOURCE_SECONDS}",
        "-an", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", str(destination),
    )


def _test_tone(destination: Path) -> None:
    _ffmpeg(
        "-f", "lavfi",
        "-i", f"sine=frequency=440:sample_rate=44100:duration={AUDIO_DURATION}",
        "-c:a", "pcm_s16le", str(destination),
    )


def _scene_preview() -> dict:
    return {
        "scene_count": 2,
        "alignment": "estimated",
        "scenes": [
            {
                "scene_number": 1,
                "start_seconds": 0,
                "end_seconds": 2,
                "assigned_material_file": "red.mp4",
                "match_status": "term_match_unverified",
            },
            {
                "scene_number": 2,
                "start_seconds": 2,
                "end_seconds": 4,
                "assigned_material_file": "green.mp4",
                "match_status": "term_match_unverified",
            },
        ],
    }


def main() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError(
            "FFmpeg e FFprobe devem estar instalados e disponíveis no PATH."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    red = OUTPUT_DIR / "red.mp4"
    green = OUTPUT_DIR / "green.mp4"
    tone = OUTPUT_DIR / "tone.wav"
    combined = OUTPUT_DIR / "scene_combined.mp4"
    final = OUTPUT_DIR / "rick_scene_final.mp4"

    print("1/5 Gerando dois vídeos locais e o áudio sintético...")
    _media_file("red", red)
    _media_file("green", green)
    _test_tone(tone)

    print("2/5 Validando as janelas e o vínculo entre cenas e arquivos...")
    sources = [str(red), str(green)]
    timeline = build_scene_render_preflight(
        _scene_preview(),
        sources,
        AUDIO_DURATION,
        max_clip_seconds=2,
    )
    if timeline["status"] != "ready_metadata_only":
        raise AssertionError(f"Plano de cenas não está pronto: {timeline['blockers']}")

    # Fail-closed guard: a missing scene MUST NOT receive generic stock media.
    missing = _scene_preview()
    missing["scenes"][1]["assigned_material_file"] = None
    missing["scenes"][1]["match_status"] = "missing_term_match"
    blocked = build_scene_render_preflight(
        missing, sources, AUDIO_DURATION, max_clip_seconds=2,
    )
    if blocked["status"] != "blocked" or blocked["segments"]:
        raise AssertionError("Cena sem material deveria bloquear a montagem")

    print("3/5 Montando cenas reais pelo MoviePy e FFmpeg...")
    used_sources: list[str] = []
    video.combine_videos(
        combined_video_path=str(combined),
        video_paths=sources,
        audio_file=str(tone),
        video_aspect=VideoAspect.portrait,
        video_concat_mode=VideoConcatMode.sequential,
        video_fit_mode=VideoFitMode.cover,
        max_clip_duration=2,
        clip_speed=1.0,
        threads=2,
        scene_timeline=timeline,
        used_video_paths=used_sources,
    )
    if used_sources != sources:
        raise AssertionError(
            f"Ordem incorreta: esperado {[p.name for p in (red, green)]}, "
            f"recebido {[Path(p).name for p in used_sources]}"
        )

    print("4/5 Adicionando o áudio de teste ao MP4...")
    params = VideoParams(
        video_subject="Teste local da montagem por cenas",
        subtitle_enabled=False,
        bgm_type="",
        bgm_volume=0,
        voice_volume=1.0,
        video_aspect=VideoAspect.portrait,
    )
    video.generate_video(
        video_path=str(combined),
        audio_path=str(tone),
        subtitle_path="",
        output_file=str(final),
        params=params,
        bgm_file_override="",
    )

    print("5/5 Validando duração, resolução, trilhas e troca de cores...")
    metadata = _probe(final)
    tracks = metadata.get("streams", [])
    picture = next((stream for stream in tracks if stream.get("codec_type") == "video"), None)
    sound = next((stream for stream in tracks if stream.get("codec_type") == "audio"), None)
    if picture is None or sound is None:
        raise AssertionError("O MP4 final deve possuir vídeo e áudio")
    if (picture["width"], picture["height"]) != (1080, 1920):
        raise AssertionError("Resolução final incorreta (esperado 1080x1920)")
    seconds = float(metadata["format"]["duration"])
    if abs(seconds - AUDIO_DURATION) > 0.35:
        raise AssertionError(f"Duração final incorreta: {seconds:.3f} s")
    red_pixel = _pixel(final, 0.75)
    green_pixel = _pixel(final, 2.75)
    if red_pixel[0] <= red_pixel[1] + 50 or red_pixel[0] <= red_pixel[2] + 50:
        raise AssertionError(f"Primeira cena não é vermelha: {red_pixel}")
    if green_pixel[1] <= green_pixel[0] + 35 or green_pixel[1] <= green_pixel[2] + 35:
        raise AssertionError(f"Segunda cena não é verde: {green_pixel}")

    report = {
        "result": "PASSOU",
        "render_type": "MP4 real com FFmpeg, arquivos sintéticos locais",
        "duration_seconds": seconds,
        "resolution": "1080x1920",
        "video_codec": picture.get("codec_name"),
        "audio_codec": sound.get("codec_name"),
        "scene_order": [Path(source).name for source in used_sources],
        "first_scene_rgb": red_pixel,
        "second_scene_rgb": green_pixel,
        "semantic_relevance_verified": False,
        "speech_alignment_verified": False,
        "output": str(final),
    }
    (OUTPUT_DIR / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print("\nTESTE E2E APROVADO — arquivo:", final)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nTESTE E2E FALHOU: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
