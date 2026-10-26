"""Actual assembly/task functions with fake clips, downloads and encoders; no media rendering."""

from contextlib import contextmanager
import itertools
import json
import math
import os
import types
import unittest
from unittest.mock import Mock, patch

from app.models import const
from app.services import media_diversity
from test.services.rick_test_support import load_functions, load_module, offline_context


class Segment:
    def __init__(self, file_path, start_time=None, end_time=None, width=None, height=None,
                 duration=None, source_file_path=None):
        self.file_path = file_path
        self.source_file_path = source_file_path or file_path
        self.start_time, self.end_time = start_time, end_time
        self.duration = end_time - start_time if duration is None else duration
        self.width, self.height = width, height


class FakeSource:
    size = (1080, 1920)
    w, h = size

    def __init__(self, duration, source):
        self.duration, self.source = duration, source

    def subclipped(self, start, end):
        return FakeSource(end - start, self.source)

    def with_speed_scaled(self, speed):
        return FakeSource(self.duration / speed, self.source)


class SerialExecutor:
    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def map(self, func, items):
        return map(func, items)


class TestMediaDiversityFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.isolation = offline_context()
        cls.addClassCleanup(cls.isolation.close)
        cls.schema = load_module("app/models/schema.py", "_rick_diversity_schema")

    def setUp(self):
        self.sources = {f"source-{index}.mp4": 4 for index in range(5)}
        self.encoder = Mock()
        names = itertools.count()

        @contextmanager
        def reserve(**kwargs):
            yield types.SimpleNamespace(name=f"encoded-{next(names)}.mp4")

        def open_source(file):
            value = self.sources[file]
            if isinstance(value, Exception):
                raise value
            return FakeSource(value, file)

        self.namespace = {
            "media_diversity": media_diversity, "math": math, "os": os, "itertools": itertools,
            "random": types.SimpleNamespace(shuffle=lambda items: None, choice=lambda items: items[0]),
            "logger": Mock(), "AudioFileClip": Mock(return_value=types.SimpleNamespace(duration=45)),
            "close_clip": Mock(), "_open_video_clip_quietly": Mock(side_effect=open_source),
            "utils": types.SimpleNamespace(normalize_clip_speed=float), "SubClippedVideoClip": Segment,
            "VideoConcatMode": self.schema.VideoConcatMode, "VideoTransitionMode": self.schema.VideoTransitionMode,
            "VideoAspect": self.schema.VideoAspect, "VideoFitMode": self.schema.VideoFitMode,
            "_get_required_video_duration": lambda duration: duration + .1,
            "_VIDEO_DURATION_SAFETY_MARGIN": .1,
            "_get_configured_video_codec": lambda: "fake", "_write_videofile_with_codec_fallback": self.encoder,
            "tempfile": types.SimpleNamespace(NamedTemporaryFile=reserve), "fps": 30,
            "logging_utils": types.SimpleNamespace(bind_log_scope=lambda func: func),
            "_get_clip_processing_concurrency": lambda: 1, "ThreadPoolExecutor": SerialExecutor,
            "_report_clip_progress": Mock(), "concat_video_clips_with_ffmpeg": Mock(), "delete_files": Mock(),
        }
        self.video = load_functions("app/services/video.py", {"combine_videos", "_prioritize_unique_source_clips"}, self.namespace)

    def combine(self, enabled=True, **options):
        self.used, self.report = [], {}
        self.video.combine_videos(
            "combined.mp4", list(self.sources), "audio.mp3", max_clip_duration=4,
            avoid_repeated_materials=enabled, material_identities=options.pop("identities", {}),
            diversity_report=self.report, used_video_paths=self.used, **options,
        )

    def test_full_assembly_45_seconds_with_5_sources(self):
        self.combine()
        self.assertEqual(len(set(self.used[:5])), 5)
        self.assertTrue(all(a != b for a, b in zip(self.used, self.used[1:])))
        self.assertEqual(self.report["unique_coverage_seconds"], 20)
        self.assertEqual(self.report["consecutive_repetitions"], 0)
        self.assertEqual(self.encoder.call_count, 5)
        self.assertEqual(self.namespace["concat_video_clips_with_ffmpeg"].call_args.kwargs["max_duration"], 45)

    def test_duplicate_renditions_are_excluded_and_only_one_source_is_reported(self):
        self.sources = {"a.mp4": 4, "a-hd.mp4": 4}
        self.combine(identities={"a.mp4": "same", "a-hd.mp4": "same"})
        self.assertEqual(self.encoder.call_count, 1)
        self.assertEqual(self.report["unique_materials"], 1)
        self.assertGreater(self.report["consecutive_repetitions"], 0)

    def test_sequential_mode_with_long_and_short_materials_rotates_sources(self):
        self.sources = {"long.mp4": 30, "short.mp4": 2}
        self.combine(video_concat_mode=self.schema.VideoConcatMode.sequential)
        self.assertEqual(set(self.used[:2]), set(self.sources))
        self.assertTrue(all(a != b for a, b in zip(self.used, self.used[1:])))
        self.assertEqual(self.report["unique_coverage_seconds"], 6)

    def test_speed_and_portrait_format_remain_supported(self):
        self.sources = {"a.mp4": 6, "b.mp4": 3}
        self.combine(clip_speed=2, video_aspect="9:16")
        self.assertTrue(all(call.args[0].size == (1080, 1920) for call in self.encoder.call_args_list))
        self.assertAlmostEqual(self.report["unique_coverage_seconds"], 4.5)

    def test_corrupt_source_does_not_block_usable_alternative(self):
        self.sources = {"broken.mp4": OSError("offline decode failure"), "usable.mp4": 4}
        self.combine()
        self.assertEqual(set(self.used), {"usable.mp4"})
        self.assertEqual(self.report["unique_materials"], 1)

    def test_encoder_failure_is_excluded_from_rotation(self):
        self.sources = {"bad.mp4": 4, "good.mp4": 4}
        self.encoder.side_effect = lambda source, *args, **kwargs: (
            (_ for _ in ()).throw(RuntimeError("mock encoding failure")) if source.source == "bad.mp4" else None
        )
        self.combine()
        self.assertEqual(set(self.used), {"good.mp4"})
        self.assertEqual(self.report["unique_materials"], 1)

    def test_empty_materials_fail_with_diagnostic_without_encoding(self):
        self.sources = {}
        with self.assertRaisesRegex(RuntimeError, "nenhum material válido"):
            self.combine()
        self.encoder.assert_not_called()
        self.assertEqual(self.report["warnings"][0]["code"], "media_diversity_empty")

    def test_disabled_feature_does_not_identify_or_plan_and_keeps_legacy_loop(self):
        with patch.object(media_diversity, "plan_timeline", side_effect=AssertionError("disabled")), \
             patch.object(media_diversity, "identify_materials", side_effect=AssertionError("disabled")):
            self.combine(False)
        self.assertEqual(self.report, {})
        self.assertEqual(self.used[:10], list(self.sources) * 2)

    def test_task_persists_report_and_exposes_warning(self):
        files = ["source-0.mp4", "source-1.mp4"]
        report = {"downloaded_unique_materials": 2, "duplicate_files": 0, "unverified_files": 0}

        def combine(**kwargs):
            kwargs["diversity_report"].update({"warnings": [
                {"code": "media_diversity_insufficient", "message": "Poucos materiais distintos."}
            ]})
            kwargs["used_video_paths"].extend(files)

        namespace = {
            "path": os.path, "utils": types.SimpleNamespace(task_dir=lambda task: "offline-task"),
            "logger": Mock(), "video": Mock(), "task_artifacts": Mock(),
            "sm": types.SimpleNamespace(state=Mock()), "VideoConcatMode": self.schema.VideoConcatMode,
            "_VIDEO_MUSIC_PROVIDERS": {}, "_stage_progress_reporter": lambda *args: None,
            "_identify_task_materials": Mock(return_value=({file: file for file in files}, report)),
        }
        namespace["video"].combine_videos.side_effect = combine
        namespace["video"].generate_video.return_value = True
        task = load_functions("app/services/task.py", {"generate_final_videos"}, namespace)
        params = self.schema.VideoParams(video_subject="Céu", video_source="pixabay", bgm_type="",
                                        avoid_repeated_materials=True)
        result = task.generate_final_videos("test", params, files, "audio.mp3", "", 45)
        self.assertEqual(result[2][0]["message"], "Poucos materiais distintos.")
        persisted = namespace["task_artifacts"].patch_script_data.call_args.kwargs["media_diversity"][0]
        self.assertEqual(persisted["selected_files"], files)
        self.assertEqual(persisted["video_index"], 1)
        params.avoid_repeated_materials = False
        namespace["video"].combine_videos.side_effect = None
        namespace["_identify_task_materials"].reset_mock()
        task.generate_final_videos("legacy", params, files, "audio.mp3", "", 45)
        namespace["_identify_task_materials"].assert_not_called()
        self.assertNotIn("avoid_repeated_materials", namespace["video"].combine_videos.call_args.kwargs)

    def test_download_failures_remain_local_and_do_not_invent_replacements(self):
        save = Mock(side_effect=["", OSError("offline"), "cached.mp4"])
        download = load_functions("app/services/material.py", {"_download_materials_in_parallel"}, {
            "save_video": save, "logger": Mock(), "_get_material_concurrency": lambda: 1,
            "_redact_request_error": lambda *args: "mock failure", "_report_material_downloaded": Mock(),
        })
        items = [types.SimpleNamespace(url=f"https://example.test/{index}", provider="pixabay") for index in range(3)]
        result = download._download_materials_in_parallel([("sky", item) for item in items], "offline-cache")
        self.assertEqual(result, [("sky", items[2], "cached.mp4")])
        self.assertEqual(save.call_count, 3)
        self.assertEqual(download._download_materials_in_parallel([], "offline-cache"), [])

    def test_identity_manifest_fallback_does_not_access_configuration(self):
        identify = Mock(return_value=({}, {}))
        namespace = {"path": os.path, "utils": types.SimpleNamespace(task_dir=lambda task: "offline-task"),
                     "json": json, "media_diversity": types.SimpleNamespace(identify_materials=identify)}
        task = load_functions("app/services/task.py", {"_identify_task_materials"}, namespace)
        with patch("builtins.open", side_effect=FileNotFoundError) as opened:
            task._identify_task_materials("test", [])
        self.assertEqual(os.path.basename(opened.call_args.args[0]), "script.json")
        identify.assert_called_once_with([], [])

    def test_ui_control_is_optional_and_does_not_change_rick_language(self):
        st = Mock()
        ui = load_functions("webui/Main.py", {"_render_media_diversity_control"}, {"st": st})
        params = self.schema.VideoParams(video_subject="Céu", video_language="pt-BR", rick_profile_enabled=True)
        self.assertFalse(params.avoid_repeated_materials)
        for enabled in (True, False):
            st.checkbox.return_value = enabled
            ui._render_media_diversity_control(params)
            self.assertEqual(params.avoid_repeated_materials, enabled)
            self.assertTrue(params.rick_profile_enabled)
            self.assertEqual(params.video_language, "pt-BR")
            self.assertEqual(st.checkbox.call_args.kwargs["key"], "avoid_repeated_materials")

    def test_all_encoder_outputs_are_cleaned_even_if_rotation_uses_only_a_subset(self):
        self.sources = {"a.mp4": 40, "b.mp4": 1}
        self.combine(video_concat_mode=self.schema.VideoConcatMode.sequential)
        encoded = {call.args[1] for call in self.encoder.call_args_list}
        self.assertEqual(set(self.namespace["delete_files"].call_args.args[0]), encoded)

    def test_zero_downloads_persist_a_coverage_warning(self):
        artifacts, state, logger = Mock(), Mock(), Mock()
        namespace = {
            "media_diversity": media_diversity, "task_artifacts": artifacts,
            "sm": types.SimpleNamespace(state=state), "logger": logger,
            "const": const, "_SUPPORTED_VIDEO_SOURCES": {"pixabay"}, "_VIDEO_MUSIC_PROVIDERS": {},
            "utils": types.SimpleNamespace(check_ffmpeg_ready=lambda: True),
            "generate_script": Mock(return_value="Roteiro fornecido."),
            "generate_terms": Mock(return_value=["sky"]), "save_script_data": Mock(),
            "generate_audio": Mock(return_value=("audio.mp3", 45, None)),
            "generate_subtitle": Mock(return_value=""), "get_video_materials": Mock(return_value=[]),
            "generate_final_videos": Mock(), "_mark_task_failed": Mock(return_value={"failed_stage": "materials"}),
        }
        task = load_functions("app/services/task.py", {"_record_empty_material_diversity", "_run_pipeline"}, namespace)
        params = self.schema.VideoParams(video_subject="Céu", video_source="pixabay", bgm_type="",
                                        subtitle_enabled=False, avoid_repeated_materials=True)
        self.assertEqual(task._run_pipeline("empty", params), {"failed_stage": "materials"})
        report = artifacts.patch_script_data.call_args.kwargs["media_diversity"][0]
        self.assertEqual(report["unique_coverage_seconds"], 0)
        self.assertEqual(report["required_seconds"], 45)
        self.assertEqual(report["warnings"][0]["code"], "media_diversity_empty")
        state.patch_task.assert_called_once_with("empty", warnings=report["warnings"])
        logger.warning.assert_called_once()
        namespace["generate_final_videos"].assert_not_called()
        namespace["get_video_materials"].assert_called_once()


if __name__ == "__main__":
    unittest.main()
