"""Offline media identity and deterministic source rotation; no provider calls."""

from collections import Counter
import hashlib
import itertools
import math
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_MEDIA_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".jpg", ".jpeg", ".png", ".bmp"}


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def url_identity(url):
    """Hash a normalized source URL; never persist URLs or authentication values."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return None
        # Even a token/query can identify the asset. Retain values in the hash
        # rather than guessing which ones are disposable authentication fields.
        query = sorted(parse_qsl(parts.query, keep_blank_values=True))
        canonical = urlunsplit((parts.scheme.lower(), parts.netloc.rsplit("@", 1)[-1].lower(),
                               parts.path, urlencode(query), ""))
        return "url:" + _digest(canonical)
    except ValueError:
        return None


def identify_materials(paths, records=()):
    """Join aliases by provider/ID, source URL, exact bytes and normalized path.

    Hash only supplied media files. Missing/unreadable files retain a path identity
    and are still subject to the existing decoder checks, never treated as valid.
    """
    paths = [str(file) for file in paths]
    name_counts = Counter(Path(file).name for file in set(paths))
    by_name = {}
    for record in records if isinstance(records, list) else ():
        if isinstance(record, dict) and isinstance(record.get("local_file"), str):
            by_name.setdefault(record["local_file"], []).append(record)
    parents = {}

    def find(key):
        parents.setdefault(key, key)
        if parents[key] != key:
            parents[key] = find(parents[key])
        return parents[key]

    aliases_by_path = {}
    unreadable = 0
    for file in dict.fromkeys(paths):
        aliases = {"path:" + _digest(os.path.normcase(os.path.realpath(file)))}
        if name_counts[Path(file).name] == 1:
            for record in by_name.get(Path(file).name, []):
                provider, asset_id = record.get("provider"), record.get("asset_id")
                if provider and asset_id not in (None, ""):
                    aliases.add("origin:" + _digest(f"{provider}:{asset_id}"))
                url = url_identity(record.get("source_page"))
                if url:
                    aliases.add(url)
        try:
            target = Path(file).resolve()
            if target.suffix.lower() not in _MEDIA_EXTENSIONS:
                raise ValueError("not a media file")
            digest = hashlib.sha256()
            with target.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            aliases.add("sha256:" + digest.hexdigest())
        except (OSError, ValueError):
            unreadable += 1
        aliases = sorted(aliases)
        root = find(aliases[0])
        for alias in aliases[1:]:
            parents[find(alias)] = root
        aliases_by_path[file] = aliases
    components = {}
    for aliases in aliases_by_path.values():
        components.setdefault(find(aliases[0]), set()).update(aliases)
    rank = {"origin": 0, "url": 1, "sha256": 2, "path": 3}
    labels = {
        root: min(aliases, key=lambda alias: (rank[alias.split(":", 1)[0]], alias))
        for root, aliases in components.items()
    }
    identities = {file: labels[find(aliases[0])] for file, aliases in aliases_by_path.items()}
    return identities, {
        "downloaded_files": len(paths),
        "downloaded_unique_materials": len(set(identities.values())),
        "duplicate_files": len(paths) - len(set(identities.values())),
        "unverified_files": unreadable,
        "materials": [{"local_file": Path(file).name, "identity": identity}
                      for file, identity in identities.items()],
    }


def _identity(clip, identities):
    return identities.get(clip.source_file_path, clip.source_file_path)


def distinct_source_clips(clips, identities):
    """Keep one readable rendition per source and interleave its distinct slices."""
    groups = {}
    for clip in clips:
        files = groups.setdefault(_identity(clip, identities), {})
        files.setdefault(clip.source_file_path, []).append(clip)
    selected = set()
    for files in groups.values():
        selected.add(max(files, key=lambda file: sum(clip.duration for clip in files[file])))
    seen = set()
    result = []
    for clip in clips:
        segment = (clip.source_file_path, clip.start_time, clip.end_time)
        if clip.source_file_path in selected and segment not in seen:
            seen.add(segment)
            result.append(clip)
    rounds = {}
    for clip in result:
        rounds.setdefault(_identity(clip, identities), []).append(clip)
    return [clip for row in itertools.zip_longest(*rounds.values()) for clip in row if clip is not None]


def plan_timeline(clips, required_seconds, identities, *, visible_seconds=None):
    """Use each source before reuse; rotate slices and avoid adjacent equal sources.

    Clips are already decoded/encoded by the existing pipeline. Reuse references
    only, so fallback requires no new downloads, encoding or paid requests.
    """
    if not math.isfinite(required_seconds) or required_seconds <= 0:
        raise ValueError("required_seconds must be finite and positive")
    target = required_seconds if visible_seconds is None else visible_seconds
    groups = {}
    for clip in clips:
        if math.isfinite(clip.duration) and clip.duration > 0:
            groups.setdefault(_identity(clip, identities), []).append(clip)
    usage = dict.fromkeys(groups, 0)
    timeline, elapsed, last = [], 0.0, None
    while groups and elapsed < required_seconds:
        candidates = [key for key in groups if key != last] or list(groups)
        key = min(candidates, key=lambda candidate: usage[candidate])
        clip = groups[key][usage[key] % len(groups[key])]
        timeline.append(clip)
        elapsed += clip.duration
        usage[key] += 1
        last = key
    visible, elapsed = [], 0.0
    for clip in timeline:
        if elapsed >= target:
            break
        visible.append(_identity(clip, identities))
        elapsed += clip.duration
    coverage = sum(max(clip.duration for clip in group) for group in groups.values())
    adjacent = sum(a == b for a, b in zip(visible, visible[1:]))
    warnings = []
    if not groups:
        warnings.append({"code": "media_diversity_empty", "message":
                         "Antirrepetição: nenhum material válido disponível; cobertura de 0 s."})
    elif coverage + 1e-9 < target:
        warnings.append({"code": "media_diversity_insufficient", "message":
                         f"Antirrepetição: {len(groups)} materiais distintos; cobertura sem reutilizar "
                         f"uma origem: {coverage:.2f} s de {target:.2f} s. "
                         "Foi necessário reutilizar materiais, alternando as origens disponíveis."})
    if adjacent:
        warnings.append({"code": "media_diversity_adjacent", "message":
                         "Antirrepetição: há somente uma origem utilizável. "
                         "Não foi possível evitar repetições consecutivas."})
    return timeline, {
        "unique_materials": len(groups), "required_seconds": target,
        "unique_coverage_seconds": coverage, "reused_occurrences": len(visible) - len(set(visible)),
        "consecutive_repetitions": adjacent, "warnings": warnings,
    }
