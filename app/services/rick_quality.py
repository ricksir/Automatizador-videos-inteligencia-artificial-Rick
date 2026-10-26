"""Rick's optional production profile. Pure rules: no configuration, I/O or APIs."""

from dataclasses import asdict, dataclass
import json
import math
from numbers import Real
import re
import unicodedata


@dataclass(frozen=True)
class RickProfile:
    profile_id: str = "rick_curiosidades"
    label: str = "Rick — Curiosidades"
    language: str = "pt-BR"
    min_seconds: float = 35.0
    max_seconds: float = 50.0
    words_per_minute: float = 150.0


PROFILE = RickProfile()

SCRIPT_INSTRUCTIONS = """# Perfil de produção: Rick — Curiosidades
- Escreva em português brasileiro natural (pt-BR), mesmo se o tema estiver em outro idioma.
- Busque uma narração de 35 a 50 segundos. Como referência inicial, use cerca de
  100 a 112 palavras, com frases curtas; a duração real será medida após a narração.
- Abra com um gancho honesto e envolvente, preferencialmente nos primeiros 3 segundos.
  Não use promessas enganosas, exageros, suspense vazio ou afirmações inventadas.
- Explique a curiosidade de forma correta e fácil de entender. Não invente fatos,
  números, fontes ou certezas; se houver incerteza, reconheça-a ou omita a afirmação.
- Use linguagem brasileira cotidiana, sem tom robótico ou formalidade excessiva.
- Termine de forma breve e interessante, sem chamadas artificiais, pedidos repetitivos
  de curtida/inscrição ou fórmulas prontas.
- Retorne somente o texto que será narrado, sem título, JSON ou instruções de cena.
- Estas regras do perfil e o idioma pt-BR têm prioridade sobre instruções conflitantes
  de idioma ou estilo nos demais requisitos do roteiro.
""".strip()


@dataclass(frozen=True)
class QualityDiagnostic:
    stage: str
    approved: bool
    code: str
    message: str
    seconds: float | None = None
    word_count: int | None = None
    profile_id: str = PROFILE.profile_id

    def to_dict(self) -> dict:
        return asdict(self)


def estimate_script_duration(script: object) -> QualityDiagnostic:
    """Estimate at 150 words/minute; never rewrite text or approve real timing."""
    if not isinstance(script, str) or not script.strip():
        return QualityDiagnostic(
            "script_estimate", False, "invalid_script",
            "Roteiro inválido: informe um texto de narração não vazio.",
        )
    text = unicodedata.normalize("NFC", script.strip())
    try:
        structured = isinstance(json.loads(text), (dict, list))
    except (ValueError, TypeError):
        structured = False
    if structured or text.startswith("```") or not any(c.isalpha() for c in text):
        return QualityDiagnostic(
            "script_estimate", False, "invalid_script",
            "Roteiro inválido: esperado texto de narração, sem JSON ou bloco de código.",
        )
    words = re.findall(r"[^\W_]+(?:['’-][^\W_]+)*", text, flags=re.UNICODE)
    seconds = len(words) * 60.0 / PROFILE.words_per_minute
    in_range = PROFILE.min_seconds <= seconds <= PROFILE.max_seconds
    position = "na faixa" if in_range else "fora da faixa"
    return QualityDiagnostic(
        "script_estimate", in_range,
        "estimated_in_range" if in_range else "estimated_outside_range",
        f"Estimativa: {seconds:.1f} s ({len(words)} palavras), {position} de 35–50 s. "
        "Referência: 150 palavras/minuto; somente o áudio medido confirma a duração.",
        seconds, len(words),
    )


def validate_audio_duration(seconds: object) -> QualityDiagnostic:
    """Accept only finite, positive measured seconds in the inclusive range."""
    if (
        isinstance(seconds, bool)
        or not isinstance(seconds, Real)
        or not math.isfinite(seconds)
        or seconds <= 0
    ):
        return QualityDiagnostic(
            "audio_duration", False, "invalid_duration",
            "Duração reprovada: não foi possível medir um áudio válido. "
            "Nenhum roteiro ou áudio será regenerado automaticamente.",
        )
    measured = float(seconds)
    approved = PROFILE.min_seconds <= measured <= PROFILE.max_seconds
    verdict = "aprovada" if approved else "reprovada"
    message = f"Duração {verdict}: {measured} s; faixa permitida: 35–50 s (inclusive)."
    if not approved:
        message += (
            " Processo interrompido antes dos materiais e da renderização. "
            "Os artefatos disponíveis foram preservados; revise o roteiro manualmente. "
            "Nenhum roteiro ou áudio será regenerado automaticamente."
        )
    return QualityDiagnostic(
        "audio_duration", approved,
        "duration_in_range" if approved else "duration_out_of_range",
        message, measured,
    )
