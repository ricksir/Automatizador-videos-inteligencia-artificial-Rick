"""Offline identity/rotation checks. Fixtures contain bytes, not generated media."""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from app.services import media_diversity as diversity
from test.services.rick_test_support import ROOT


def clip(source, duration, start=0, file=None):
    return SimpleNamespace(source_file_path=source, file_path=file or source,
                           duration=duration, start_time=start, end_time=start + duration)


class TestMediaIdentity(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix=".rick-media-test-", dir=ROOT)
        self.assertTrue(Path(directory.name).resolve().is_relative_to(ROOT))
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def media(self, name, content):
        target = self.directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return str(target)

    def test_same_origin_id_links_different_renditions(self):
        files = [self.media("one.mp4", b"one rendition"), self.media("two.mp4", b"other rendition")]
        records = [{"provider": "pixabay", "asset_id": 123, "local_file": Path(file).name} for file in files]
        identities, report = diversity.identify_materials(files, records)
        self.assertEqual(identities[files[0]], identities[files[1]])
        self.assertEqual(report["duplicate_files"], 1)
        self.assertTrue(identities[files[0]].startswith("origin:"))

    def test_bytes_and_repeated_paths_link_without_metadata(self):
        first = self.media("a.mp4", b"identical bytes")
        second = self.media("b.mp4", b"identical bytes")
        third = self.media("c.mp4", b"different")
        identities, report = diversity.identify_materials([first, second, first, third])
        self.assertEqual(identities[first], identities[second])
        self.assertNotEqual(identities[first], identities[third])
        self.assertEqual(report["downloaded_unique_materials"], 2)
        self.assertEqual(report["duplicate_files"], 2)

    def test_source_url_is_normalized_and_never_persisted(self):
        files = [self.media("one.mp4", b"one"), self.media("two.mp4", b"two")]
        records = [
            {"local_file": "one.mp4", "source_page": "https://EXAMPLE.test/video?id=5&token=fake-secret#top"},
            {"local_file": "two.mp4", "source_page": "https://example.test/video?token=fake-secret&id=5"},
        ]
        identities, report = diversity.identify_materials(files, records)
        self.assertEqual(identities[files[0]], identities[files[1]])
        self.assertTrue(identities[files[0]].startswith("url:"))
        self.assertNotIn("fake-secret", json.dumps(report))
        self.assertNotEqual(diversity.url_identity("https://example.test/video?id=5"),
                            diversity.url_identity("https://example.test/video?id=6"))
        self.assertNotEqual(diversity.url_identity("https://example.test/video?token=asset-a"),
                            diversity.url_identity("https://example.test/video?token=asset-b"))

    def test_transitive_id_and_content_aliases_are_merged(self):
        files = [self.media("a.mp4", b"a"), self.media("b.mp4", b"b"), self.media("c.mp4", b"b")]
        records = [{"local_file": Path(file).name, "provider": "pixabay", "asset_id": asset}
                   for file, asset in zip(files, [1, 1, 3])]
        identities, _ = diversity.identify_materials(files, records)
        self.assertEqual(len(set(identities.values())), 1)

    def test_ids_are_scoped_by_provider(self):
        files = [self.media("a.mp4", b"a"), self.media("b.mp4", b"b")]
        records = [{"local_file": Path(file).name, "provider": provider, "asset_id": 1}
                   for file, provider in zip(files, ["pixabay", "local"])]
        identities, _ = diversity.identify_materials(files, records)
        self.assertNotEqual(identities[files[0]], identities[files[1]])

    def test_same_basename_does_not_merge_unrelated_directories(self):
        files = [self.media("one/a.mp4", b"one"), self.media("two/a.mp4", b"two")]
        records = [{"local_file": "a.mp4", "provider": "pixabay", "asset_id": 1}]
        identities, _ = diversity.identify_materials(files, records)
        self.assertEqual(len(set(identities.values())), 2)

    def test_empty_missing_and_nonmedia_inputs(self):
        self.assertEqual(diversity.identify_materials([])[1]["downloaded_unique_materials"], 0)
        files = [str(self.directory / "missing.mp4"), str(self.directory / "not-media.txt")]
        identities, report = diversity.identify_materials(files)
        self.assertEqual(report["unverified_files"], 2)
        self.assertTrue(all(value.startswith("path:") for value in identities.values()))


class TestMediaTimeline(unittest.TestCase):
    def test_issue_45_seconds_five_materials_four_second_cuts(self):
        materials = [clip(str(index), 4) for index in range(5)]
        timeline, report = diversity.plan_timeline(materials, 45.1, {}, visible_seconds=45)
        sources = [item.source_file_path for item in timeline]
        self.assertEqual(sources[:5], [str(index) for index in range(5)])
        self.assertTrue(all(a != b for a, b in zip(sources, sources[1:])))
        self.assertEqual(report["unique_coverage_seconds"], 20)
        self.assertEqual(report["reused_occurrences"], 7)
        self.assertEqual(report["consecutive_repetitions"], 0)
        self.assertEqual(report["warnings"][0]["code"], "media_diversity_insufficient")
        self.assertEqual(sources, [item.source_file_path for item in diversity.plan_timeline(materials, 45.1, {})[0]])

    def test_different_durations_are_used_until_covered(self):
        timeline, report = diversity.plan_timeline([clip("a", 1.5), clip("b", 4)], 12, {})
        self.assertGreaterEqual(sum(item.duration for item in timeline), 12)
        self.assertEqual([item.source_file_path for item in timeline[:4]], ["a", "b", "a", "b"])
        self.assertEqual(report["unique_coverage_seconds"], 5.5)

    def test_empty_or_invalid_decoded_clips_emit_clear_warning(self):
        for materials in ([], [clip("a", 0), clip("b", float("nan"))]):
            timeline, report = diversity.plan_timeline(materials, 45, {})
            self.assertEqual(timeline, [])
            self.assertEqual(report["warnings"][0]["code"], "media_diversity_empty")

    def test_single_material_fallback_is_explicit(self):
        timeline, report = diversity.plan_timeline([clip("a", 4)], 10, {})
        self.assertEqual(len(timeline), 3)
        self.assertEqual(report["consecutive_repetitions"], 2)
        self.assertIn("media_diversity_adjacent", [item["code"] for item in report["warnings"]])

    def test_safety_margin_does_not_create_false_visible_reuse_warning(self):
        timeline, report = diversity.plan_timeline([clip("a", 4), clip("b", 4)], 8.1, {}, visible_seconds=8)
        self.assertEqual(len(timeline), 3)
        self.assertEqual(report["reused_occurrences"], 0)
        self.assertEqual(report["warnings"], [])

    def test_distinct_renditions_and_slices_are_interleaved(self):
        materials = [clip("a", 2), clip("b", 4), clip("a-hd", 4), clip("a-hd", 4, start=4)]
        selected = diversity.distinct_source_clips(materials, {"a": "same", "a-hd": "same"})
        self.assertNotIn("a", [item.source_file_path for item in selected])
        self.assertEqual(len(selected), 3)
        self.assertNotEqual(selected[0].source_file_path, selected[1].source_file_path)


if __name__ == "__main__":
    unittest.main()
