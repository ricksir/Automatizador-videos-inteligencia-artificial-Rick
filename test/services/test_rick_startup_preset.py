"""Offline verification of the one-time Rick startup preference profile."""

import unittest

from app.services.rick_startup_preset import (
    PRESET_MARKER,
    PRESET_VERSION,
    RICK_STARTUP_DEFAULTS,
    pending_startup_settings,
)


class TestRickStartupPreset(unittest.TestCase):
    def test_first_run_contains_expected_safe_preferences(self):
        settings = pending_startup_settings({})
        values = {(section, name): value for section, name, value in settings}
        self.assertEqual(len(values), len(settings))
        self.assertTrue(values["ui", "rick_profile_enabled"])
        self.assertTrue(values["ui", "avoid_repeated_materials"])
        self.assertEqual(values["ui", "video_language"], "pt-BR")
        self.assertEqual(values["ui", "video_aspect_pixabay"], "9:16")
        self.assertEqual(values["ui", "video_clip_duration"], 4)
        self.assertEqual(values["ui", "tts_server"], "gemini-tts")
        self.assertEqual(values["ui", "voice_name"], "gemini:Charon-Informative")
        self.assertEqual(values["ui", "font_size"], 55)
        self.assertEqual(values["ui", "bgm_type"], "")
        self.assertFalse(values["app", "upload_post_auto_upload"])
        self.assertEqual(values["app", "video_source"], "pixabay")
        self.assertTrue(values["app", "match_materials_to_script"])

    def test_marked_config_is_never_overwritten_on_restart(self):
        saved = {
            PRESET_MARKER: PRESET_VERSION,
            "rick_profile_enabled": False,
            "avoid_repeated_materials": False,
            "video_clip_duration": 6,
        }
        self.assertEqual(pending_startup_settings(saved), ())

    def test_unrelated_settings_and_secrets_are_never_part_of_preset(self):
        for section, defaults in RICK_STARTUP_DEFAULTS.items():
            self.assertIn(section, {"ui", "app"})
            for name in defaults:
                self.assertFalse(any(
                    secret in name.lower()
                    for secret in ("api_key", "password", "token", "secret", "proxy")
                ))
                self.assertNotIn(name, {"video_subject", "video_script", "video_terms"})

    def test_version_marker_enables_first_application_once(self):
        self.assertTrue(pending_startup_settings({}))
        self.assertTrue(pending_startup_settings({PRESET_MARKER: 0}))
        self.assertFalse(pending_startup_settings({PRESET_MARKER: PRESET_VERSION}))


if __name__ == "__main__":
    unittest.main()
