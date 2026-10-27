"""Fail-closed, offline safety check for potentially sensitive *tracked* files.

Never prints suspected values or excerpts. This is defense in depth: use
GitHub secret scanning, push protection and full-history checks separately.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

MAX_BYTES = 2 * 1024 * 1024

BAD_BASENAMES = {
    ".env", "config.toml", "secrets.toml", "credentials.json",
    "service_account.json", "token.json", "tokens.json",
    "auth.json", "id_rsa", "id_ed25519",
}
BAD_SUFFIXES = {".pem", ".p12", ".pfx", ".kdbx"}
BAD_PARTS = {".ssh", ".aws", ".azure", "storage", "logs"}
TOKEN_PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN (?:[A-Z0-9 ]* )?PRIVATE KEY-----"),
    "github_token": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
    "openai_token": re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
    "google_api_key": re.compile(rb"AIza[A-Za-z0-9_-]{35}"),
    "aws_access_key": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "slack_token": re.compile(rb"xox[baprs]-[A-Za-z0-9-]{24,}"),
}
# Avoid false positives from discussing credentials in documentation; the
# actual secret values must still NEVER be committed anywhere.
SCAN_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".json", ".toml", ".yaml",
                 ".yml", ".ps1", ".bat", ".sh", ".env", ".txt"}
SCAN_NAMES = {"Dockerfile", ".gitmodules"}


def risky_path(raw: str) -> bool:
    normalized = raw.replace("\\", "/").strip("/")
    if not normalized or normalized.startswith("../"):
        return True
    p = PurePosixPath(normalized)
    lower_parts = {v.lower() for v in p.parts}
    if lower_parts & BAD_PARTS:
        return True
    name = p.name.lower()
    return (
        name in BAD_BASENAMES
        or name.startswith(".env.")
        or name.startswith("config.toml.")
        or name.endswith(".key")
        or name.endswith(tuple(BAD_SUFFIXES))
        or ("service-account" in name and name.endswith(".json"))
        or ("service_account" in name and name.endswith(".json"))
    )


def secret_categories(blob: bytes) -> list[str]:
    """Report types, never values, hashes, file paths or offsets."""
    return [name for name, pattern in TOKEN_PATTERNS.items()
            if pattern.search(blob)]


def check_tracked(root: Path) -> tuple[int, int, int]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached"],
        cwd=root, capture_output=True, check=True,
    )
    unsafe_paths = 0
    suspected_files = 0
    unreadable_files = 0
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        name = raw.decode("utf-8", errors="surrogateescape")
        if risky_path(name):
            unsafe_paths += 1
            continue
        p = root / name
        try:
            if p.is_symlink() or not p.is_file():
                unreadable_files += 1
                continue
            if p.stat().st_size > MAX_BYTES:
                # Large locked binaries are handled by source-specific tools.
                continue
            if p.suffix.lower() not in SCAN_SUFFIXES and p.name not in SCAN_NAMES:
                continue
            if secret_categories(p.read_bytes()):
                suspected_files += 1
        except (OSError, ValueError):
            unreadable_files += 1
    return unsafe_paths, suspected_files, unreadable_files


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        unsafe, suspected, unreadable = check_tracked(root)
    except (OSError, subprocess.SubprocessError):
        print("Segurança: não foi possível avaliar os arquivos versionados.")
        return 1
    if unsafe or suspected or unreadable:
        print(
            "Segurança: verificação bloqueada. "
            f"Arquivos de risco: {unsafe}; possíveis segredos: {suspected}; "
            f"arquivos inacessíveis: {unreadable}."
        )
        print(
            "Inspecione localmente os arquivos rastreados antes de publicar. "
            "Nenhum segredo ou conteúdo suspeito será exibido no log."
        )
        return 1
    print(
        "Segurança: verificação preventiva de caminhos e padrões concluída. "
        "Isto não substitui a varredura do histórico completo."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
