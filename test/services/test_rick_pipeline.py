"""Execute actual pipeline functions with offline stage mocks and temporary artifacts."""

import copy
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.models import const
from app.services import rick_quality
from test.services.rick_test_support import ROOT, load_functions, load_module, offline_context


class TestRickPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.isolation = offline_context()
        cls.addClassCleanup(cls.isolation.close)
        cls.schema = load_module("app/models/schema.py", "_rick_pipeline_schema")
        cls.artifacts = load_module("app/services/task_artifacts.py", "_rick_pipeline_artifacts")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix=".rick-offline-", dir=ROOT)
        self.assertTrue(Path(temporary.name).resolve().is_relative_to(ROOT))
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.audio = self.directory / "audio.mp3"
        self.audio.write_bytes(b"offline fixture; never synthesized or decoded")
        directory_patch = patch.object(self.artifacts.utils, "task_dir", return_value=str(self.directory))
        directory_patch.start()
        self.addCleanup(directory_patch.stop)
        self.records = {}

        def update(task_id, **fields):
            self.records.setdefault(task_id, {}).update(copy.deepcopy(fields))

        state = types.SimpleNamespace(
            update_task=Mock(side_effect=update),
            patch_task=Mock(side_effect=update),
            get_task=lambda task_id: copy.deepcopy(self.records.get(task_id)),
        )
        self.namespace = {
            "const": const, "rick_quality": rick_quality, "logger": Mock(),
            "sm": types.SimpleNamespace(state=state), "llm": Mock(),
            "task_artifacts": self.artifacts,
            "utils": types.SimpleNamespace(check_ffmpeg_ready=Mock(return_value=True)),
            "video": Mock(), "voice": Mock(),
            "generate_terms": Mock(return_value=["blue sky"]),
            "generate_audio": Mock(return_value=(str(self.audio), 35, object())),
            "generate_subtitle": Mock(return_value="subtitle.srt"),
            "get_video_materials": Mock(return_value=["offline-clip.mp4"]),
            "generate_final_videos": Mock(return_value=(["final.mp4"], ["combined.mp4"], [])),
            "_schedule_cross_post": Mock(side_effect=AssertionError("No uploads")),
            "upload_post": types.SimpleNamespace(upload_post_service=Mock()),
            "VideoConcatMode": self.schema.VideoConcatMode,
            "_SUPPORTED_VIDEO_SOURCES": {"pixabay", "local"},
            "_VIDEO_MUSIC_PROVIDERS": {},
            "_TASK_FAILURE_STATE_WRITE_ATTEMPTS": 1,
        }
        self.namespace["voice"].get_audio_duration.return_value = 42.75
        self.namespace["upload_post"].upload_post_service.is_configured.return_value = False
        self.namespace["llm"].generate_script.return_value = "Você sabia? Dá pra entender o céu azul!"
        self.task = load_functions(
            "app/services/task.py",
            {"generate_script", "save_script_data", "_mark_task_failed", "_run_pipeline", "start"},
            self.namespace,
        )

    def params(self, enabled=True, **overrides):
        fields = dict(
            video_subject="Por que o céu é azul?", video_script="Você sabia? O céu é azul!",
            rick_profile_enabled=enabled, video_source="pixabay", subtitle_enabled=False, bgm_type="",
        )
        fields.update(overrides)
        return self.schema.VideoParams(**fields)

    def manifest(self):
        return json.loads((self.directory / "script.json").read_text(encoding="utf-8"))

    def assert_no_downstream_work(self):
        self.namespace["generate_subtitle"].assert_not_called()
        self.namespace["get_video_materials"].assert_not_called()
        self.namespace["generate_final_videos"].assert_not_called()
        self.namespace["_schedule_cross_post"].assert_not_called()
        self.namespace["upload_post"].upload_post_service.is_configured.assert_not_called()

    def test_rejects_fractional_audio_before_materials_and_keeps_artifacts(self):
        for duration in (34.9999, 50.0001):
            with self.subTest(duration=duration):
                self.namespace["voice"].get_audio_duration.return_value = duration
                task_id = f"rejected-{duration}"
                result = self.task.start(task_id, self.params())
                self.assertEqual(result["failed_stage"], "rick_audio_quality", result)
                self.assertEqual(result["state"], const.TASK_STATE_FAILED)
                self.assertEqual(result["audio_duration"], duration)
                self.assertEqual(result["audio_file"], str(self.audio))
                self.assertIn("antes dos materiais", result["error"])
                self.assertEqual(self.audio.read_bytes(), b"offline fixture; never synthesized or decoded")
                self.assertEqual(self.manifest()["script"], self.params().video_script)
                self.assertEqual(self.manifest()["rick_quality"]["audio_duration"]["seconds"], duration)
                self.assertEqual(self.records[task_id]["rick_quality"], result["rick_quality"])
                self.assert_no_downstream_work()
        self.assertEqual(self.namespace["generate_audio"].call_count, 2)
        self.namespace["llm"].generate_script.assert_not_called()

    def test_inclusive_boundaries_and_fractional_success_reach_render(self):
        for duration in (35.0, 35.0001, 42.789, 49.9999, 50.0):
            with self.subTest(duration=duration):
                self.namespace["voice"].get_audio_duration.return_value = duration
                result = self.task.start(f"approved-{duration}", self.params())
                self.assertEqual(result["videos"], ["final.mp4"], result)
                self.assertEqual(result["audio_duration"], duration)
                self.assertTrue(result["rick_quality"]["audio_duration"]["approved"])
                self.assertEqual(self.namespace["get_video_materials"].call_args.args[3], duration)
                self.assertEqual(self.namespace["generate_final_videos"].call_args.args[5], duration)
        self.assertEqual(self.namespace["generate_audio"].call_count, 5)
        self.namespace["_schedule_cross_post"].assert_not_called()

    def test_disabled_profile_does_not_remeasure_or_reject_legacy_duration(self):
        self.namespace["voice"].get_audio_duration.side_effect = AssertionError("No Rick measurement")
        self.namespace["generate_audio"].return_value = (str(self.audio), 80, object())
        result = self.task.start("legacy", self.params(False))
        self.assertEqual(result["videos"], ["final.mp4"])
        self.assertEqual(result["audio_duration"], 80)
        self.assertNotIn("rick_quality", result)
        self.assertNotIn("rick_quality", self.manifest())
        self.namespace["voice"].get_audio_duration.assert_not_called()

    def test_estimate_outside_range_does_not_reject_valid_measured_audio(self):
        result = self.task.start("estimate-only", self.params(), stop_at="audio")
        self.assertFalse(result["rick_quality"]["script_estimate"]["approved"])
        self.assertTrue(result["rick_quality"]["audio_duration"]["approved"])
        self.assertEqual(result["audio_duration"], 42.75)
        self.namespace["generate_audio"].assert_called_once()

    def test_invalid_manual_script_stops_before_tts_and_is_preserved(self):
        result = self.task.start("invalid-script", self.params(video_script="..."))
        self.assertEqual(result["failed_stage"], "rick_script_quality")
        self.assertEqual(self.manifest()["script"], "...")
        self.namespace["generate_audio"].assert_not_called()
        self.namespace["llm"].generate_script.assert_not_called()
        self.assert_no_downstream_work()

    def test_invalid_or_unreadable_measurement_stops_without_regeneration(self):
        for duration in (None, float("nan"), float("inf"), 0, -1):
            with self.subTest(duration=duration):
                self.namespace["voice"].get_audio_duration.return_value = duration
                result = self.task.start(f"invalid-{duration}", self.params())
                self.assertEqual(result["failed_stage"], "rick_audio_quality")
                self.assertEqual(result["rick_quality"]["audio_duration"]["code"], "invalid_duration")
                self.assertIsNone(self.manifest()["rick_quality"]["audio_duration"]["seconds"])
        self.namespace["voice"].get_audio_duration.side_effect = OSError("unreadable fixture")
        result = self.task.start("unreadable", self.params())
        self.assertEqual(result["failed_stage"], "rick_audio_quality")
        self.assertTrue(self.audio.exists())
        self.assert_no_downstream_work()

    def test_reused_preview_is_remeasured_instead_of_trusting_rounded_duration(self):
        self.namespace["voice"].get_audio_duration.return_value = 34.9
        preview = {"duration": 35}
        result = self.task.start("preview", self.params(), voice_preview=preview)
        self.assertEqual(result["audio_duration"], 34.9)
        self.namespace["generate_audio"].assert_called_once()
        self.assertIs(self.namespace["generate_audio"].call_args.kwargs["voice_preview"], preview)
        self.namespace["voice"].get_audio_duration.assert_called_once_with(str(self.audio))
        self.assert_no_downstream_work()

    def test_script_only_saves_estimate_without_tts(self):
        result = self.task.start("script-only", self.params(), stop_at="script")
        self.assertIn("script_estimate", result["rick_quality"])
        self.assertNotIn("audio_duration", result["rick_quality"])
        self.assertEqual(self.manifest()["script"], self.params().video_script)
        self.namespace["generate_audio"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
