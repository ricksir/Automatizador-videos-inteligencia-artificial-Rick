"""Mock the media IO while executing the real combine_videos function body.

No ffmpeg, codecs, cloud providers or network required. Only fake readers and
writers run; the implementation under test is loaded from its real source AST.
"""

import itertools
import math
import os
import random
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from pathlib import Path
from unittest.mock import Mock

from app.services import rick_scene_render
from test.services.rick_test_support import ROOT, load_functions


class Aspect(str, Enum):
    portrait = "9:16"

    def to_resolution(self):
        return 1080, 1920


class ConcatMode(str, Enum):
    random = "random"
    sequential = "sequential"


class FitMode(str, Enum):
    cover = "cover"


class TransitionMode(str, Enum):
    fade_in = "fade_in"
    fade_out = "fade_out"
    slide_in = "slide_in"
    slide_out = "slide_out"
    zoom_in = "zoom_in"
    zoom_out = "zoom_out"
    shuffle = "shuffle"


class Clip:
    def __init__(self, duration=20.0):
        self.duration = duration
        self.size = (1080, 1920)
        self.w, self.h = self.size

    def subclipped(self, start, end):
        return Clip(end - start)

    def with_speed_scaled(self, factor):
        return Clip(self.duration / factor)


class Slice:
    def __init__(
        self, file_path, start_time=None, end_time=None,
        width=None, height=None, duration=None, source_file_path=None,
    ):
        self.file_path = file_path
        self.start_time = start_time
        self.end_time = end_time
        self.width = width
        self.height = height
        self.duration = duration if duration is not None else end_time - start_time
        self.source_file_path = source_file_path or file_path


class TestSceneRendererWithFakeMedia(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT, prefix=".rick-scene-video-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.source_a = str(self.directory / "book.mp4")
        self.source_b = str(self.directory / "election.mp4")
        self.output = str(self.directory / "combined.mp4")
        self.concatenation = Mock()
        self.encoder = Mock()
        self.reader = Mock(side_effect=lambda source: Clip())
        self.deleted = []
        self.used = []

        def cleanup(files):
            for file in set(files if isinstance(files, list) else [files]):
                self.deleted.append(file)
                Path(file).unlink(missing_ok=True)

        ns = {
            "math": math,
            "os": os,
            "tempfile": tempfile,
            "random": random,
            "itertools": itertools,
            "logger": Mock(),
            "fps": 30,
            "ThreadPoolExecutor": ThreadPoolExecutor,
            "logging_utils": types.SimpleNamespace(bind_log_scope=lambda fn: fn),
            "AudioFileClip": lambda filename: Clip(8),
            "VideoAspect": Aspect,
            "VideoConcatMode": ConcatMode,
            "VideoFitMode": FitMode,
            "VideoTransitionMode": TransitionMode,
            "SubClippedVideoClip": Slice,
            "close_clip": lambda reader: None,
            "rick_scene_render": rick_scene_render,
            "utils": types.SimpleNamespace(normalize_clip_speed=lambda value: float(value)),
            "_VIDEO_DURATION_SAFETY_MARGIN": 0.1,
            "_get_required_video_duration": lambda secs: float(secs) + 0.1,
            "_open_video_clip_quietly": self.reader,
            "_get_clip_processing_concurrency": lambda: 1,
            "_get_configured_video_codec": lambda: "libx264",
            "_write_videofile_with_codec_fallback": self.encoder,
            "concat_video_clips_with_ffmpeg": self.concatenation,
            "delete_files": cleanup,
            "_report_clip_progress": Mock(),
            "_prioritize_unique_source_clips": lambda subclipped_items, concat_mode, **_: subclipped_items,
        }
        self.renderer = load_functions("app/services/video.py", {"combine_videos"}, ns).combine_videos

    def timeline(self):
        return {
            "status": "ready_metadata_only",
            "scene_count": 2,
            "duration_seconds": 8,
            "segments": [
                {"scene_number": 1, "source_file": "book.mp4", "start_seconds": 0, "end_seconds": 4, "duration_seconds": 4},
                {"scene_number": 2, "source_file": "election.mp4", "start_seconds": 4, "end_seconds": 8, "duration_seconds": 4},
            ],
        }

    def combine(self, **overrides):
        opts = dict(
            combined_video_path=self.output,
            video_paths=[self.source_a, self.source_b],
            audio_file="fake.mp3",
            video_aspect="9:16",
            video_concat_mode="sequential",
            video_fit_mode="cover",
            video_transition_mode=None,
            max_clip_duration=4,
            used_video_paths=self.used,
            scene_timeline=self.timeline(),
        )
        opts.update(overrides)
        return self.renderer(**opts)

    def test_uses_only_assigned_assets_and_preserves_scene_order(self):
        result = self.combine()
        self.assertEqual(result, self.output)
        self.assertEqual(self.concatenation.call_count, 1)
        # Two 4s scene clips + a separate 100ms codec safety slice.
        self.assertEqual(self.encoder.call_count, 3)
        self.assertEqual(self.used, [self.source_a, self.source_b])
        self.assertEqual(self.concatenation.call_args.kwargs["max_duration"], 8)
        self.assertEqual(len(self.concatenation.call_args.kwargs["clip_files"]), 3)

    def test_missing_assigned_video_fails_before_encoding_or_concatenation(self):
        with self.assertRaisesRegex(ValueError, "candidate not found"):
            self.combine(video_paths=[self.source_a])
        self.encoder.assert_not_called()
        self.concatenation.assert_not_called()

    def test_partial_encode_failure_does_not_fallback_or_concatenate(self):
        self.encoder.side_effect = [None, RuntimeError("simulated broken decoder"), None]
        with self.assertRaisesRegex(RuntimeError, "Montagem por cenas interrompida"):
            self.combine()
        self.concatenation.assert_not_called()

    def test_default_mode_still_uses_original_path(self):
        self.combine(scene_timeline=None)
        self.assertTrue(self.concatenation.called)

    def test_short_source_can_loop_only_within_its_assigned_scene(self):
        self.reader.side_effect = lambda src: Clip(1.5 if src == self.source_a else 20)
        self.combine()
        self.assertTrue(self.concatenation.called)
        # Repeats of book.mp4 must occur before election.mp4, not after it.
        self.assertEqual(self.used[:3], [self.source_a] * 3)
        self.assertEqual(self.used[-1], self.source_b)


if __name__ == "__main__":
    unittest.main()
