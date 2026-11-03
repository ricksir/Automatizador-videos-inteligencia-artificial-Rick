"""Rick daily unattended production controller (disabled unless configured).

This is a *durable run-once process*, meant to be invoked by an OS scheduler.
It does NOT itself install a scheduler, enable publishing, bypass media review,
or promise that a third-party platform accepted the video. A single durable
daily ledger keeps duplicate submissions from silently occurring after a crash.

Publishing requires a separate machine-quality receipt, including semantic
scene matching, rights provenance and timing validation. The current image
carousel cannot produce that receipt, so it cannot silently become a daily post.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import config
from app.models.schema import VideoParams, VideoAspect
from app.services import state as sm
from app.services import task as tasks
from app.services import upload_post

_PLATFORMS = ("youtube", "instagram", "tiktok")
_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}\Z")
_MAX_LEDGER_BYTES = 100_000
_MAX_POLICY_BYTES = 40_000


def load_policy(path: str | Path) -> dict:
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > _MAX_POLICY_BYTES:
        raise ValueError("Configuração do piloto inexistente ou inválida.")
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Versão inválida do piloto diário.")
    if type(data.get("enabled")) is not bool or type(data.get("publish_enabled")) is not bool:
        raise ValueError("Habilitação e publicação devem ser booleanas.")
    timezone = data.get("timezone")
    if not isinstance(timezone, str) or not 3 <= len(timezone) <= 60:
        raise ValueError("Fuso horário inválido.")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Fuso indisponível. Instale os dados de timezone (tzdata).") from exc
    topics = data.get("topics")
    if (
        not isinstance(topics, list) or not 1 <= len(topics) <= 365
        or any(not isinstance(t, str) or not 8 <= len(t.strip()) <= 180 for t in topics)
    ):
        raise ValueError("Configure entre 1 e 365 temas válidos.")
    platforms = data.get("platforms")
    if (not isinstance(platforms, list) or not platforms
            or len(platforms) != len(set(map(str, platforms)))
            or any(p not in _PLATFORMS for p in platforms)):
        raise ValueError("Plataformas devem ser uma lista sem duplicações.")
    # VideoParams is a Pydantic model; we only pass explicitly user-owned
    # settings and disallow server-side file paths and any manual-upload input.
    template = data.get("video_params")
    if not isinstance(template, dict):
        raise ValueError("Parâmetros de produção inválidos.")
    if any(k in template for k in ("custom_audio_file", "video_materials", "video_script")):
        raise ValueError("O piloto não aceita material nem áudio por caminho externo.")
    if template.get("video_source") not in ("pexels", "pixabay", "coverr"):
        raise ValueError("Piloto restrito a fontes de banco com origem registrada.")
    # Safety defaults must not be overridden by configuration.
    for key in ("video_count", "rick_scene_render_enabled"):
        if key in template and template[key] not in (1 if key == "video_count" else False,):
            raise ValueError(f"Parâmetro automático não autorizado: {key}")
    return data


def _topic_for_day(policy: dict, today: date) -> str:
    # Stable across restarts. Users must refresh the topic list if exhausted;
    # the pilot never invents facts or silently repeats topics on the 366th day.
    start = policy.get("start_date")
    if not isinstance(start, str):
        raise ValueError("A data inicial deve ser informada.")
    try:
        first = date.fromisoformat(start)
    except ValueError as exc:
        raise ValueError("Data inicial inválida.") from exc
    elapsed = (today - first).days
    if elapsed < 0:
        raise ValueError("O piloto ainda não chegou à data inicial.")
    if elapsed >= len(policy["topics"]):
        raise ValueError(
            "Banco de temas esgotado. Não repetirei vídeos sem renovar os temas."
        )
    return policy["topics"][elapsed].strip()


def _write_json_atomic(path: Path, value: dict) -> None:
    temp = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent,
            prefix=".rick-daily-", suffix=".tmp", delete=False,
        ) as handle:
            temp = Path(handle.name)
            json.dump(value, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        temp = None
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _read_ledger(path: Path) -> dict | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_LEDGER_BYTES:
        raise ValueError("Registro diário alterado ou inválido.")
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or record.get("version") != 1:
        raise ValueError("Registro diário inválido.")
    return record


class _ExclusiveRun:
    """Atomic lock across processes; crashed locks require investigation."""

    def __init__(self, directory: Path):
        self.path = directory / ".rick-daily.lock"
        self.owns = False

    def __enter__(self):
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise RuntimeError(
                "Já existe execução ou bloqueio anterior. Verifique o PID e os logs "
                "antes de liberar a trava; não execute dois pilotos simultaneamente."
            ) from exc
        self.owns = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(f"pid={os.getpid()} at={datetime.now().isoformat()}\n")
        return self

    def __exit__(self, *_args):
        if self.owns:
            self.path.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_video(video_path: str | Path) -> dict:
    """Verify MP4/AV content, not its editorial relevance or license."""
    path = Path(video_path)
    if not path.is_file() or path.is_symlink() or path.suffix.casefold() != ".mp4":
        raise ValueError("MP4 final não encontrado.")
    if not 0 < path.stat().st_size <= 2 * 1024**3:
        raise ValueError("Arquivo MP4 com tamanho inválido.")
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_name,codec_type,width,height:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True, timeout=30,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    if not isinstance(streams, list):
        raise ValueError("Streams de vídeo inválidos.")
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
    try:
        duration = float(data["format"]["duration"])
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("Duração ausente do MP4.") from exc
    if (
        len(videos) != 1 or not audios
        or videos[0].get("codec_name") != "h264"
        or not any(stream.get("codec_name") == "aac" for stream in audios)
        or not 15 <= duration <= 180
        or not isinstance(videos[0].get("width"), int)
        or not isinstance(videos[0].get("height"), int)
        or videos[0]["width"] >= videos[0]["height"]
    ):
        raise ValueError("MP4 não atende ao perfil vertical H.264/AAC de 15–180 s.")
    return {
        "video_sha256": _sha256(path),
        "duration_seconds": round(duration, 3),
        "resolution": [videos[0]["width"], videos[0]["height"]],
    }


def verify_quality_receipt(receipt: str | Path | None, video_sha256: str) -> bool:
    """Fail closed if no independent automatic editorial/rights verdict exists.

    This module cannot truthfully infer semantic relevance from the filename.
    Future QA implementations must produce a machine-verifiable receipt. A
    mere successful render or metadata search is NOT an editorial pass.
    """
    if not isinstance(receipt, (str, Path)):
        return False
    src = Path(receipt)
    if src.is_symlink() or not src.is_file() or src.stat().st_size > 100_000:
        return False
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return False
    return (
        isinstance(data, dict)
        and data.get("version") == 1
        and data.get("video_sha256") == video_sha256
        and data.get("status") == "passed"
        and data.get("semantic_scene_match") is True
        and data.get("audio_timing_verified") is True
        and data.get("source_rights_verified") is True
        and data.get("no_unsafe_content") is True
        and data.get("qa_engine") not in (None, "", "metadata_only")
    )


def _generate_video(topic: str, template: dict, task_id: str) -> dict:
    """Use existing LLM/TTS/material/render pipeline; never cross-post here."""
    if upload_post.upload_post_service.auto_upload:
        raise ValueError(
            "Desative upload_post_auto_upload: o piloto controla a publicação "
            "por plataforma para evitar duas postagens."
        )
    requested = {
        **template, "video_subject": topic,
        "rick_profile_enabled": True,
        "video_aspect": VideoAspect.portrait,
        "video_count": 1,
        "match_materials_to_script": True,
        "avoid_repeated_materials": True,
        "bgm_type": template.get("bgm_type", ""),
    }
    params = VideoParams.model_validate(requested)
    sm.state.update_task(task_id, video_subject=topic)
    with config.runtime_config_lock():
        result = tasks.start(task_id, params)
    if not isinstance(result, dict) or not result.get("videos"):
        raise RuntimeError("A produção automática não entregou vídeo final.")
    produced = result["videos"]
    if not isinstance(produced, list) or len(produced) != 1:
        raise RuntimeError("O piloto exige exatamente um vídeo por execução.")
    return {"video_path": produced[0], "quality_receipt": None}


def _publish_one(platform: str, path: str, title: str) -> dict:
    service = upload_post.UploadPostService()
    if not service.is_configured():
        raise ValueError("Upload-Post sem conta e autorização configuradas.")
    return service.upload_video(
        path, title, platforms=[platform],
        youtube_extra=({
            "selfDeclaredMadeForKids": service.youtube_made_for_kids,
            "privacyStatus": service.youtube_privacy_status,
        } if platform == "youtube" else None),
    )


def run_once(
    policy: dict,
    state_dir: str | Path,
    *,
    today: date | None = None,
    generate=None,
    publish=None,
    quality_check=None,
) -> dict:
    """At most one generation and one submission per platform per local day.

    State is persisted BEFORE any expensive generation or outbound POST.
    An interrupted submission is UNKNOWN, never automatically resubmitted.
    """
    if not isinstance(policy, dict) or policy.get("enabled") is not True:
        return {"status": "disabled"}
    try:
        local_today = today or datetime.now(ZoneInfo(policy["timezone"])).date()
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Timezone não disponível no sistema.") from exc
    topic = _topic_for_day(policy, local_today)
    root = Path(state_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise ValueError("Pasta de estados não autorizada.")
    ledger = root / f"{local_today.isoformat()}.json"
    generate = generate or _generate_video
    publish = publish or _publish_one
    quality_check = quality_check or verify_quality_receipt

    with _ExclusiveRun(root):
        state = _read_ledger(ledger)
        if state is None:
            state = {
                "version": 1, "date": local_today.isoformat(),
                "topic": topic, "status": "new",
                "task_id": "rick-daily-" + local_today.strftime("%Y%m%d") + "-" + uuid4().hex[:8],
                "platforms": {p: "not_started" for p in policy["platforms"]},
                "publish_requests": {},
            }
            _write_json_atomic(ledger, state)
        if state.get("topic") != topic or state.get("date") != local_today.isoformat():
            raise ValueError("A programação do dia foi alterada após o início.")

        if state.get("status") == "new":
            state["status"] = "rendering"
            _write_json_atomic(ledger, state)
            try:
                produced = generate(topic, policy["video_params"], state["task_id"])
                path = produced["video_path"]
                path_obj = Path(path).resolve(strict=True)
                if path_obj.suffix.casefold() != ".mp4" or not path_obj.is_file():
                    raise ValueError("Gerador retornou caminho de vídeo inválido.")
                state["video_path"] = str(path_obj)
                state["quality_receipt"] = produced.get("quality_receipt")
                state["status"] = "rendered"
                _write_json_atomic(ledger, state)
            except Exception as exc:
                state["status"] = "generation_failed"
                state["error"] = f"{type(exc).__name__}: {exc}"[:300]
                _write_json_atomic(ledger, state)
                return state
        if state["status"] == "rendering":
            # Process termination after the generation was submitted is not
            # proof that no MP4 exists. Never start another creation blindly.
            state["status"] = "generation_unconfirmed"
            _write_json_atomic(ledger, state)
            return state
        if state["status"] not in ("rendered", "quality_blocked", "publishing", "published"):
            return state

        # Never publish without a complete independent quality receipt.
        if state.get("status") in ("rendered", "quality_blocked"):
            try:
                video_info = validate_video(state["video_path"])
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                state["status"] = "quality_blocked"
                state["error"] = f"Vídeo inválido: {exc}"[:300]
                _write_json_atomic(ledger, state)
                return state
            state["video_sha256"] = video_info["video_sha256"]
            if not quality_check(state.get("quality_receipt"), video_info["video_sha256"]):
                state["status"] = "quality_blocked"
                state["error"] = "Sem laudo automático confiável de cena/tempo/direitos; publicação bloqueada."
                _write_json_atomic(ledger, state)
                return state
            state["status"] = "publishing"
            state.pop("error", None)
            _write_json_atomic(ledger, state)

        if policy.get("publish_enabled") is not True:
            # A dry operation must never send a remote request.
            state["status"] = "ready_not_authorized"
            _write_json_atomic(ledger, state)
            return state
        if upload_post.upload_post_service.auto_upload:
            raise ValueError("Cross-posting global deve estar desligado para evitar duplicações.")
        if not upload_post.UploadPostService().is_configured() and publish is _publish_one:
            state["status"] = "blocked_credentials"
            _write_json_atomic(ledger, state)
            return state

        # A previous "submitting" status means an interrupted process might
        # already have delivered the POST. Do not automatically retry it.
        for platform in policy["platforms"]:
            prior = state["platforms"].get(platform)
            if prior in ("published", "unknown", "submitting", "failed"):
                continue
            if prior != "not_started":
                raise ValueError("Estado por plataforma inválido no registro diário.")
            state["platforms"][platform] = "submitting"
            _write_json_atomic(ledger, state)
            try:
                result = publish(platform, state["video_path"], topic)
            except Exception as exc:
                result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            if not isinstance(result, dict):
                result = {"success": False, "error": "Resposta de publicação inválida"}
            request_id = result.get("request_id")
            if isinstance(request_id, str):
                state["publish_requests"][platform] = request_id[:100]
            if result.get("success") is True:
                state["platforms"][platform] = "published"
            else:
                # Only an explicit, certain server rejection can be retried
                # manually; uncertain outcomes remain never-autoretry.
                state["platforms"][platform] = "unknown" if request_id else "failed"
                state.setdefault("platform_errors", {})[platform] = str(
                    result.get("error") or "Resposta não confirmada"
                )[:250]
            _write_json_atomic(ledger, state)
        state["status"] = (
            "published" if all(value == "published" for value in state["platforms"].values())
            else "publication_incomplete"
        )
        _write_json_atomic(ledger, state)
        return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Rick - execução diária com registro e anti-duplicação")
    parser.add_argument("--policy", default="config/rick_daily.example.json")
    parser.add_argument("--state-dir", default="storage/rick_autopilot")
    parser.add_argument("--execute", action="store_true", help="executar geração; ainda exige habilitação no JSON")
    args = parser.parse_args()
    policy = load_policy(args.policy)
    if not args.execute:
        print(json.dumps({
            "status": "dry_run",
            "enabled": policy["enabled"],
            "publish_enabled": policy["publish_enabled"],
            "platforms": policy["platforms"],
            "topic_count": len(policy["topics"]),
        }, ensure_ascii=False))
        return 0
    result = run_once(policy, args.state_dir)
    print(json.dumps({
        "status": result["status"], "date": result.get("date"),
        "platforms": result.get("platforms"),
        "error": result.get("error"),
    }, ensure_ascii=False))
    return 0 if result["status"] in ("published", "disabled", "ready_not_authorized") else 1


if __name__ == "__main__":
    raise SystemExit(main())
