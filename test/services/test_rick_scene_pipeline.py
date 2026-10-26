"""Regression tests for the optional 02B2A pipeline integration (no APIs)."""

import ast
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from app.services import rick_scene_assignment, rick_scene_plan


def _load_preview_handler(tmp_path):
    filepath = Path(__file__).resolve().parents[2] / "app" / "services" / "task.py"
    tree = ast.parse(filepath.read_text(encoding="utf-8"))
    function = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef)
        and item.name == "_record_rick_scene_candidate_preview"
    )
    module = ast.Module(body=[function], type_ignores=[])
    writer = Mock(return_value=True)
    log = Mock()
    namespace = {
        "rick_scene_plan": rick_scene_plan,
        "rick_scene_assignment": rick_scene_assignment,
        "task_artifacts": SimpleNamespace(patch_script_data=writer),
        "logger": log,
        "re": re,
        "json": json,
        "path": os.path,
        "utils": SimpleNamespace(task_dir=lambda task_id: str(tmp_path)),
    }
    exec(compile(module, str(filepath), "exec"), namespace)
    return namespace["_record_rick_scene_candidate_preview"], writer, log


def _params(**kwargs):
    default = {"match_materials_to_script": True, "video_source": "pixabay", "video_clip_duration": 4}
    default.update(kwargs)
    return SimpleNamespace(**default)


def test_successful_download_creates_a_preview_without_changing_video_paths(tmp_path):
    script = "Gramsci escreveu sobre ideias. Uma eleição envolve discursos e escolhas."
    records = [
        {"local_file": "books.mp4", "provider": "pixabay", "asset_id": "5", "search_term": "books"},
        {"local_file": "vote.mp4", "provider": "pixabay", "asset_id": "6", "search_term": "election"},
        {"local_file": "random.mp4", "provider": "pixabay", "asset_id": "7", "search_term": "sunset"},
    ]
    (tmp_path / "script.json").write_text(
        json.dumps({"material_sources": records}), encoding="utf-8"
    )
    fn, writer, log = _load_preview_handler(tmp_path)
    original_files = [str(tmp_path / "books.mp4"), str(tmp_path / "vote.mp4")]
    before = list(original_files)
    fn("task-123", _params(), script, ["books", "election"], 8.0, original_files)
    assert original_files == before
    writer.assert_called_once()
    args, kwargs = writer.call_args
    assert args == ("task-123",)
    preview = kwargs["rick_scene_candidate_preview"]
    assert preview["scene_count"] == 2
    assert [scene["assigned_material_file"] for scene in preview["scenes"]] == [
        "books.mp4", "vote.mp4"
    ]
    assert preview["status"] == "preview_only_not_rendered"
    assert kwargs["rick_scene_plan"]["scenes"][0]["text"].startswith("Gramsci")
    assert all(not item["media_verified"] for item in preview["scenes"])
    assert not log.warning.called


def test_disabled_matching_does_not_read_or_save(tmp_path):
    fn, writer, log = _load_preview_handler(tmp_path)
    fn("task-456", _params(match_materials_to_script=False), "Roteiro.", ["books"], 5, [])
    writer.assert_not_called()
    log.warning.assert_not_called()


def test_other_video_sources_not_affected(tmp_path):
    fn, writer, log = _load_preview_handler(tmp_path)
    for source in ("local", "openai_image", "wavespeed"):
        fn("task-456", _params(video_source=source), "Roteiro.", ["books"], 5, [])
    writer.assert_not_called()
    log.warning.assert_not_called()


def test_missing_manifest_cannot_break_video_generation(tmp_path):
    fn, writer, log = _load_preview_handler(tmp_path)
    fn("task-789", _params(), "Trabalho e cultura.", ["work"], 4, [])
    writer.assert_not_called()
    log.warning.assert_called_once()
    assert "FileNotFoundError" in log.warning.call_args.args


def test_task_wires_preview_after_successful_download_but_before_returning_materials():
    path = Path(__file__).resolve().parents[2] / "app" / "services" / "task.py"
    contents = path.read_text(encoding="utf-8")
    call = contents.index('    _record_rick_scene_candidate_preview(\n        task_id,')
    materials_return = contents.index('    if stop_at == "materials":', call)
    assert call < materials_return
    assert "rick_scene_candidate_preview" in contents
