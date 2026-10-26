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

    def test_webui_applies_settings_once_without_touching_credentials(self):
        import ast
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import Mock
        from app.services import rick_startup_preset

        root = Path(__file__).resolve().parents[2]
        source = (root / "webui" / "Main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        target = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_apply_rick_startup_preset_once"
        )
        module = ast.Module(body=[target], type_ignores=[])
        existing = {"groq_api_key": "do-not-change", "gemini_api_key": "keep"}
        config = SimpleNamespace(app=existing, ui={})
        recorded = []
        def update(section, key, value):
            recorded.append((section, key, value))
            getattr(config, section)[key] = value
            return True

        save = Mock()
        namespace = {
            "config": config,
            "rick_startup_preset": rick_startup_preset,
            "_set_runtime_config": update,
            "_save_runtime_config": save,
            "logger": Mock(),
        }
        exec(compile(module, str(root / "webui" / "Main.py"), "exec"), namespace)
        apply = namespace["_apply_rick_startup_preset_once"]
        self.assertTrue(apply())
        self.assertEqual(config.ui[PRESET_MARKER], PRESET_VERSION)
        self.assertEqual(config.ui["video_clip_duration"], 4)
        self.assertEqual(config.app["groq_api_key"], "do-not-change")
        self.assertEqual(config.app["gemini_api_key"], "keep")
        self.assertEqual(config.app["video_source"], "pixabay")
        save.assert_called_once()

        config.ui["rick_profile_enabled"] = False
        config.ui["avoid_repeated_materials"] = False
        config.ui["video_clip_duration"] = 5
        recorded.clear()
        self.assertFalse(apply())
        self.assertFalse(recorded)
        self.assertFalse(config.ui["rick_profile_enabled"])
        self.assertFalse(config.ui["avoid_repeated_materials"])
        self.assertEqual(config.ui["video_clip_duration"], 5)
        save.assert_called_once()

    def test_webui_persists_both_rick_checkboxes(self):
        from pathlib import Path

        source = (Path(__file__).resolve().parents[2] / "webui" / "Main.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '_set_runtime_config("ui", "rick_profile_enabled", params.rick_profile_enabled)',
            source,
        )
        self.assertIn(
            '_set_runtime_config("ui", "avoid_repeated_materials", params.avoid_repeated_materials)',
            source,
        )
        self.assertIn("if _apply_rick_startup_preset_once():", source)
        self.assertIn("rick_startup_preset.seed_startup_widgets(", source)
        self.assertIn("_initialize_session_state()\n\n\ndef tr(", source)


    def test_replayed_browser_widget_state_is_replaced_on_upgrade_only(self):
        from app.services.rick_startup_preset import seed_startup_widgets

        # Simulate previously saved widgets from the pre-Rick interface.
        session = {
            "rick_profile_enabled": False,
            "avoid_repeated_materials": False,
            "match_materials_to_script": False,
            "subtitle_enabled_checkbox": False,
            "font_size_slider": 30,
            "video_clip_duration_select_pt": 2,
            "tts_server_select_pt": "azure-tts-v1",
            "voice_volume_select_pt": 0.6,
        }
        def setter(name, value):
            session[name + "_pt"] = value

        self.assertTrue(pending_startup_settings({PRESET_MARKER: 1}))
        seed_startup_widgets(session, setter)
        self.assertTrue(session["rick_profile_enabled"])
        self.assertTrue(session["avoid_repeated_materials"])
        self.assertTrue(session["match_materials_to_script"])
        self.assertTrue(session["subtitle_enabled_checkbox"])
        self.assertEqual(session["font_size_slider"], 55)
        self.assertEqual(session["video_clip_duration_select_pt"], 4)
        self.assertEqual(session["tts_server_select_pt"], "gemini-tts")
        self.assertEqual(session["voice_volume_select_pt"], 1.0)
        self.assertEqual(session["voice_rate_select_pt"], 1.0)
        self.assertEqual(session["speech_synthesis_select_gemini-tts_pt"], "gemini:Charon-Informative")
        self.assertEqual(session["video_source_select_pt"], "pixabay")
        self.assertEqual(session["video_aspect_for_pixabay_pt"], "9:16")
        self.assertIsNone(session["video_transition_mode_select_pt"])

        # Once upgraded, the user may opt out and new launches must not reset.
        saved = {PRESET_MARKER: PRESET_VERSION}
        session["rick_profile_enabled"] = False
        session["video_clip_duration_select_pt"] = 5
        self.assertEqual(pending_startup_settings(saved), ())
        self.assertFalse(session["rick_profile_enabled"])
        self.assertEqual(session["video_clip_duration_select_pt"], 5)

    def test_update_occurs_before_first_widget_render(self):
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        source = (root / "webui" / "Main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        app = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                   and node.name == "_render_application")
        statements = app.body
        self.assertIsInstance(statements[1], ast.If)
        self.assertIsInstance(statements[2], ast.Expr)
        self.assertEqual(statements[2].value.func.id, "_render_top_bar")
        self.assertIn("_initialize_session_state()\n\n\ndef tr(", source)

    def test_version_marker_enables_first_application_once(self):
        self.assertTrue(pending_startup_settings({}))
        self.assertTrue(pending_startup_settings({PRESET_MARKER: 0}))
        self.assertFalse(pending_startup_settings({PRESET_MARKER: PRESET_VERSION}))


if __name__ == "__main__":
    unittest.main()
