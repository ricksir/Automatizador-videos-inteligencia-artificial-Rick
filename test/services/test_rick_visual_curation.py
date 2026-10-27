"""Deterministic/offline regression for compact Rick visual-curation UI."""
from __future__ import annotations

import unittest

from app.services.rick_visual_curation import (
    commons_search_url,
    inspect_visual_scenes,
    person_anchor,
    retained_human_decisions,
)


class VisualCurationTests(unittest.TestCase):
    def setUp(self):
        self.scenes = [
            {"text": "Gramsci estudou as ideias", "search_term": "Gramsci theory",
             "assigned_material_file": "a.mp4", "material_reused": False},
            {"text": "A sociedade e as suas ideias", "search_term": "nature waterfall",
             "assigned_material_file": "b.mp4", "material_reused": False},
            {"text": "Gramsci escreveu", "search_term": "Gramsci theory",
             "assigned_material_file": "a.mp4", "material_reused": True},
            {"text": "O contexto da eleição", "search_term": "Gramsci Brazil",
             "assigned_material_file": None, "material_reused": False},
        ]
        self.sources = [
            {"local_file": "a.mp4", "provider": "pixabay",
             "asset_id": 123, "search_term": "Gramsci theory"},
            {"local_file": "b.mp4", "provider": "pixabay",
             "asset_id": 124, "search_term": "nature waterfall"},
        ]

    def test_person_anchor_case_insensitive_in_portuguese(self):
        self.assertEqual(
            person_anchor("O que o filósofo gramsci e seu livro têm em comum?"),
            "Gramsci",
        )
        self.assertIsNone(person_anchor("Por que o céu é azul?"))
        self.assertIsNone(person_anchor("Quem foi o filósofo?"))

    def test_report_flags_unrelated_term_and_duplicates(self):
        r = inspect_visual_scenes(
            "O que o filósofo gramsci escreveu?", self.scenes, self.sources
        )
        self.assertEqual(r["scenes_total"], 4)
        self.assertEqual(r["subject_anchor"], "Gramsci")
        self.assertEqual(r["unique_source_identities"], 2)
        self.assertEqual(r["reused_source_occurrences"], 1)
        self.assertTrue(r["scenes"][1]["issues"])
        self.assertIn("reutilização de origem", r["scenes"][2]["issues"])
        self.assertIsNone(r["scenes"][3]["candidate"])
        self.assertTrue(r["scenes"][0]["historical_image_search_url"])
        self.assertTrue(all(s["review_required"] for s in r["scenes"]))

    def test_never_mistakes_metadata_for_visual_confirmation(self):
        r = inspect_visual_scenes("Céu azul", [
            {"text": "O céu é azul", "search_term": "blue sky",
             "assigned_material_file": "sky.mp4"},
        ], [{"local_file": "sky.mp4", "search_term": "blue sky"}])
        self.assertIsNone(r["subject_anchor"])
        self.assertFalse(r["scenes"][0]["issues"])
        self.assertTrue(r["scenes"][0]["review_required"])
        self.assertIsNone(r["scenes"][0]["historical_image_search_url"])

    def test_missing_candidate_is_flagged(self):
        r = inspect_visual_scenes("Gramsci", [
            {"text": "Gramsci", "search_term": "Gramsci",
             "assigned_material_file": "missing.mp4"},
        ], [])
        self.assertIsNone(r["scenes"][0]["candidate"])
        self.assertIn("sem candidato correspondente no manifesto", r["scenes"][0]["issues"])

    def test_commons_url_is_fixed_hostname_and_encodes_query(self):
        url = commons_search_url('Gramsci "portrait"')
        self.assertTrue(url.startswith("https://commons.wikimedia.org/w/index.php?"))
        self.assertIn("Gramsci", url)
        with self.assertRaises(ValueError):
            commons_search_url("   ")

    def test_bounded_and_invalid_input(self):
        with self.assertRaises(ValueError):
            inspect_visual_scenes("X", [{}] * 61, [])
        with self.assertRaises(ValueError):
            inspect_visual_scenes("X", [{"text": ""}], "not a list")

    def test_retains_only_human_decisions_and_excludes_edited_scene(self):
        saved = [
            {"editorial_review": "approved_by_human",
             "assigned_material_file": "a.mp4",
             "editorial_source_note": "Fonte e licença verificadas",
             "editorial_content_checked": True,
             "editorial_rights_checked": True},
            {"editorial_review": "unreviewed",
             "assigned_material_file": "b.mp4"},
            {"editorial_review": "rejected"},
        ]
        self.assertEqual(
            retained_human_decisions(saved, exclude_scene=1),
            [{"scene_number": 3, "decision": "reject"}],
        )
        previous = retained_human_decisions(saved, exclude_scene=2)
        self.assertEqual([v["scene_number"] for v in previous], [1, 3])
        self.assertTrue(previous[0]["content_checked"])
        self.assertTrue(previous[0]["rights_checked"])
        self.assertEqual(previous[0]["selected_file"], "a.mp4")

    def test_no_automatic_generation_or_secrets(self):
        # Importing the module never fetches, converts, publishes or chooses
        # downloaded video files. Any selected file still needs human review.
        r = inspect_visual_scenes("", [], [])
        self.assertEqual(r["scenes_total"], 0)
        self.assertEqual(r["reused_source_occurrences"], 0)


if __name__ == "__main__":
    unittest.main()
