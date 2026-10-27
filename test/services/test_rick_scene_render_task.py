"""No-network tests for Rick's opt-in render preparation and task dispatch."""

import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.services import rick_scene_timeline
from test.services.rick_test_support import ROOT, load_functions


def example_preview():
    return {
        "alignment": "estimated",
        "scene_count": 2,
        "scenes": [
            {
                "start_seconds": 0, "end_seconds": 4, "scene_number": 1,
                "assigned_material_file": "book.mp4",
                "match_status": "term_match_unverified",
            },
            {
                "start_seconds": 4, "end_seconds": 8, "scene_number": 2,
                "assigned_material_file": "vote.mp4",
                "match_status": "term_match_unverified",
            },
        ],
    }


def params(**values):
    defaults = {
        "rick_scene_render_enabled": True,
        "match_materials_to_script": True,
        "video_source": "pixabay",
        "video_count": 1,
        "video_clip_duration": 4,
        "avoid_repeated_materials": False,
        "bgm_type": "",
        "bgm_volume": 0,
        "video_concat_mode": "random",
        "video_transition_mode": None,
        "video_aspect": "9:16",
        "video_fit_mode": "cover",
        "n_threads": 1,
        "video_clip_speed": 1.0,
    }
    defaults.update(values)
    return types.SimpleNamespace(**defaults)


class TestRickSceneRenderTask(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT, prefix=".rick-render-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patches = Mock()
        namespace = {
            "logger": Mock(),
            "json": json,
            "path": os.path,
            "utils": types.SimpleNamespace(task_dir=lambda _: str(self.root)),
            "rick_scene_timeline": rick_scene_timeline,
            "task_artifacts": types.SimpleNamespace(patch_script_data=self.patches),
        }
        funcs = load_functions(
            "app/services/task.py", {"_prepare_rick_scene_render"}, namespace
        )
        self.prepare = funcs._prepare_rick_scene_render

    def save(self, preview=None):
        (self.root / "script.json").write_text(
            json.dumps({"rick_scene_candidate_preview": preview or example_preview()}),
            encoding="utf-8",
        )

    def test_ready_plan_is_returned_and_recorded_before_encoding(self):
        self.save()
        out = self.prepare(
            "offline", params(), [r"C:\tmp\book.mp4", r"C:\tmp\vote.mp4"], 8.0
        )
        assert out["status"] == "ready_metadata_only"
        assert out["scene_count"] == 2
        self.patches.assert_called_once()
        assert self.patches.call_args.kwargs["rick_scene_render_preflight"] == out

    def test_opt_out_never_attempts_to_read_manifest(self):
        assert self.prepare("offline", params(rick_scene_render_enabled=False), [], 8) is None
        self.patches.assert_not_called()

    def test_missing_preview_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Prévia de cenas"):
            self.prepare("offline", params(), ["book.mp4"], 8)

    def test_missing_query_candidate_blocks_without_fallback(self):
        preview = example_preview()
        preview["scenes"][1]["match_status"] = "missing_term_match"
        preview["scenes"][1]["assigned_material_file"] = None
        self.save(preview)
        with self.assertRaisesRegex(ValueError, "cenas \\[2\\]"):
            self.prepare("offline", params(), ["book.mp4", "vote.mp4"], 8)

    def test_experimental_mode_rejects_unapproved_providers_and_batch(self):
        for invalid in (
            params(video_source="local"),
            params(video_source="openai_image"),
            params(match_materials_to_script=False),
            params(video_count=2),
        ):
            with self.subTest(source=invalid.video_source, batch=invalid.video_count):
                with self.assertRaises(ValueError):
                    self.prepare("offline", invalid, [], 8)
        self.patches.assert_not_called()

    def test_generate_final_videos_passes_scene_plan_only_when_opted_in(self):
        prepare = Mock(return_value={"status": "ready_metadata_only", "scene_count": 2, "segments": []})
        combine = Mock()
        generate = Mock(return_value=True)
        state = types.SimpleNamespace(update_task=Mock())
        namespace = {
            "logger": Mock(),
            "path": os.path,
            "utils": types.SimpleNamespace(task_dir=lambda _: str(self.root)),
            "_prepare_rick_scene_render": prepare,
            "_VIDEO_MUSIC_PROVIDERS": {},
            "bgm_service": Mock(),
            "sm": types.SimpleNamespace(state=state),
            "video": types.SimpleNamespace(combine_videos=combine, generate_video=generate),
            "_stage_progress_reporter": Mock(return_value=None),
            "VideoConcatMode": types.SimpleNamespace(sequential="sequential", random="random"),
        }
        funcs = load_functions("app/services/task.py", {"generate_final_videos"}, namespace)
        param = params()
        files = ["book.mp4", "vote.mp4"]
        videos, combined, warnings = funcs.generate_final_videos(
            "task-id", param, files, "voice.mp3", "", 8.0,
        )
        assert len(videos) == 1
        assert len(combined) == 1
        assert not warnings
        assert combine.call_args.kwargs["scene_timeline"]["status"] == "ready_metadata_only"
        assert prepare.call_count == 1

        combine.reset_mock()
        param.rick_scene_render_enabled = False
        funcs.generate_final_videos("task-id", param, files, "voice.mp3", "", 8.0)
        assert "scene_timeline" not in combine.call_args.kwargs


if __name__ == "__main__":
    unittest.main()
