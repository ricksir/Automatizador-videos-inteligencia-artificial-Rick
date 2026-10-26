"""Pure offline rules; imports no application config or provider clients."""

import unittest

from app.services.rick_quality import PROFILE, estimate_script_duration, validate_audio_duration


class TestRickQuality(unittest.TestCase):
    def test_profile_contract(self):
        self.assertEqual(PROFILE.language, "pt-BR")
        self.assertEqual(PROFILE.label, "Rick — Curiosidades")
        self.assertEqual((PROFILE.min_seconds, PROFILE.max_seconds), (35.0, 50.0))

    def test_short_target_and_long_estimates(self):
        for count, expected in ((10, False), (100, True), (200, False)):
            with self.subTest(count=count):
                result = estimate_script_duration("curiosidade " * count)
                self.assertEqual(result.approved, expected)
                self.assertEqual(result.word_count, count)
                self.assertEqual(result.seconds, count * 0.4)
                self.assertIn("somente o áudio medido", result.message)

    def test_empty_and_malformed_scripts(self):
        for script in (None, [], {}, 123, "", "   ", "...", "123", '[]',
                       '{"roteiro": "Olá"}', '```texto\nOlá\n```'):
            with self.subTest(script=script):
                result = estimate_script_duration(script)
                self.assertFalse(result.approved)
                self.assertEqual(result.code, "invalid_script")
                self.assertIsNone(result.seconds)

    def test_accents_and_brazilian_expressions_are_preserved(self):
        script = "Você sabia? O céu é azul. Pois é, dá pra entender!"
        original = script
        result = estimate_script_duration(script)
        self.assertEqual(result.word_count, 11)
        self.assertEqual(script, original)
        self.assertEqual(
            estimate_script_duration("céu ação você").word_count,
            estimate_script_duration("ce\u0301u ac\u0327a\u0303o voce\u0302").word_count,
        )

    def test_measured_inclusive_and_fractional_boundaries(self):
        for seconds, expected in ((34.9999, False), (35, True), (35.0001, True),
                                  (42.789, True), (49.9999, True), (50, True),
                                  (50.0001, False)):
            with self.subTest(seconds=seconds):
                result = validate_audio_duration(seconds)
                self.assertEqual(result.approved, expected)
                self.assertEqual(result.seconds, seconds)
                self.assertIn(str(float(seconds)), result.message)

    def test_invalid_measured_durations(self):
        for seconds in (None, "40", True, False, 0, -1, float("nan"),
                        float("inf"), float("-inf"), [], {}):
            with self.subTest(seconds=seconds):
                result = validate_audio_duration(seconds)
                self.assertFalse(result.approved)
                self.assertEqual(result.code, "invalid_duration")
                self.assertIsNone(result.to_dict()["seconds"])

    def test_rejection_explains_preservation_and_no_regeneration(self):
        result = validate_audio_duration(51.25)
        self.assertIn("artefatos disponíveis foram preservados", result.message)
        self.assertIn("antes dos materiais", result.message)
        self.assertIn("regenerado automaticamente", result.message)


if __name__ == "__main__":
    unittest.main()
