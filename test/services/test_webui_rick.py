"""WebUI functions with fake Streamlit; no app startup, credentials or APIs."""

from collections.abc import Mapping
import hashlib
import types
import unittest
from unittest.mock import MagicMock, Mock

from app.models import const
from app.services import rick_quality
from test.services.rick_test_support import load_functions, load_module, offline_context


class TestWebuiRick(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.isolation = offline_context()
        cls.addClassCleanup(cls.isolation.close)
        cls.schema = load_module("app/models/schema.py", "_rick_webui_schema")

    def setUp(self):
        self.st = MagicMock()
        self.st.session_state = {
            "rick_profile_enabled": False, "ui_language": "pt", "video_subject": "Céu",
            "video_script": "Você sabia? Dá pra entender o céu azul!",
            "video_terms": "sky", "custom_system_prompt": "", "video_script_prompt": "",
            "script_language_select_pt": "en-US",
        }
        self.st.checkbox.side_effect = lambda label, **kw: self.st.session_state[kw["key"]]
        self.st.text_area.side_effect = lambda label, **kw: self.st.session_state.get(kw["key"], "")
        self.st.selectbox.side_effect = lambda label, **kw: self.st.session_state[kw["key"]]
        self.st.slider.return_value = 1
        self.st.button.return_value = False
        left, right = MagicMock(), MagicMock()
        left.button.return_value = right.button.return_value = False
        self.st.columns.return_value = (left, right)
        llm = Mock(
            MIN_SCRIPT_PARAGRAPH_NUMBER=1, MAX_SCRIPT_PARAGRAPH_NUMBER=10,
            MAX_SCRIPT_PROMPT_LENGTH=2000, MAX_SCRIPT_SYSTEM_PROMPT_LENGTH=8000,
            DEFAULT_SCRIPT_SYSTEM_PROMPT="Default original prompt",
        )
        self.namespace = {
            "st": self.st, "Mapping": Mapping, "rick_quality": rick_quality,
            "config": types.SimpleNamespace(ui={"video_language": "en-US"}),
            "tr": lambda text: text, "tr_optional": lambda text: text,
            "support_locales": ["en-US"], "llm": llm,
            "_saved_ui_choice": lambda key, options, default: "en-US",
            "_set_runtime_config": Mock(), "_open_settings_dialog": Mock(),
            "_effective_script_generation_backend": Mock(return_value="local"),
            "_script_generation_method_help": Mock(return_value="help"),
            "reset_script_system_prompt": Mock(), "render_script_prompt_preview": Mock(),
            "_render_local_script_generation": Mock(), "_render_loomloom_script_generation": Mock(),
        }
        self.ui = load_functions(
            "webui/Main.py",
            {"localized_widget_key", "stable_selectbox", "_sync_rick_profile_language",
             "_render_rick_quality", "_render_script_settings"},
            self.namespace,
        )

    def render(self, enabled):
        self.st.session_state["rick_profile_enabled"] = enabled
        params = self.schema.VideoParams(video_subject="")
        self.ui._render_script_settings(MagicMock(), params)
        return params

    def test_enabled_profile_shows_estimate_preserves_script_and_does_not_save_language(self):
        original = self.st.session_state["video_script"]
        params = self.render(True)
        self.assertTrue(params.rick_profile_enabled)
        self.assertEqual(params.video_language, "pt-BR")
        self.assertEqual(params.video_script, original)
        self.st.checkbox.assert_called_once()
        self.assertEqual(self.st.checkbox.call_args.args[0], "Rick — Curiosidades")
        self.assertTrue(any("Estimativa:" in str(call) for call in self.st.warning.call_args_list))
        self.assertFalse(any(
            call.args[:2] == ("ui", "video_language")
            for call in self.namespace["_set_runtime_config"].call_args_list
        ))
        self.namespace["llm"].generate_script.assert_not_called()

    def test_toggle_restores_original_language_and_keeps_ptbr_option(self):
        self.render(True)
        self.render(True)
        params = self.render(False)
        self.assertFalse(params.rick_profile_enabled)
        self.assertEqual(params.video_language, "en-US")
        self.assertEqual(self.st.session_state["script_language_select_pt"], "en-US")
        self.assertNotIn("rick_previous_script_language", self.st.session_state)
        language_calls = [call for call in self.st.selectbox.call_args_list if call.args[0] == "Script Language"]
        for call in language_calls:
            self.assertIn("pt-BR", call.kwargs["options"])
            self.assertEqual(call.kwargs["format_func"]("pt-BR"), "Português (Brasil)")
        self.assertFalse(language_calls[-1].kwargs["disabled"])

    def test_disabled_profile_retains_original_language_and_has_no_estimate(self):
        params = self.render(False)
        self.assertEqual(params.video_language, "en-US")
        self.st.info.assert_not_called()
        self.st.warning.assert_not_called()
        self.namespace["_set_runtime_config"].assert_any_call("ui", "video_language", "en-US")

    def test_duration_diagnostics_are_rendered_as_success_or_error(self):
        for duration, approved in ((35, True), (50, True), (34.9999, False), (50.0001, False)):
            with self.subTest(duration=duration):
                self.st.reset_mock()
                diagnostic = rick_quality.validate_audio_duration(duration).to_dict()
                self.ui._render_rick_quality({"audio_duration": diagnostic})
                renderer = self.st.success if approved else self.st.error
                renderer.assert_called_once_with(diagnostic["message"])

    def test_missing_diagnostics_do_not_add_ui_messages(self):
        for value in (None, {}, [], "invalid"):
            self.ui._render_rick_quality(value)
        self.st.info.assert_not_called()
        self.st.warning.assert_not_called()
        self.st.success.assert_not_called()
        self.st.error.assert_not_called()

    def test_failed_task_exposes_preserved_audio_and_diagnostic(self):
        logs = Mock()
        ui = load_functions(
            "webui/Main.py", {"_render_generation_task_snapshot"},
            dict(self.namespace, const=const, _normalize_task_state=int,
                 _render_generation_logs=logs, os=types.SimpleNamespace(path=types.SimpleNamespace(isfile=lambda p: True))),
        )
        diagnostic = rick_quality.validate_audio_duration(34.9).to_dict()
        ui._render_generation_task_snapshot("offline", {
            "state": const.TASK_STATE_FAILED, "error": diagnostic["message"],
            "audio_file": "offline-audio.mp3", "rick_quality": {"audio_duration": diagnostic},
        })
        self.st.audio.assert_called_once_with("offline-audio.mp3")
        self.st.error.assert_any_call(diagnostic["message"])
        logs.assert_called_once_with("offline")

    def test_script_button_forwards_profile_to_configured_llm(self):
        self.st.button.return_value = True
        llm = self.namespace["llm"]
        llm.generate_script.return_value = "Você sabia? O céu é azul!"
        llm.generate_terms.return_value = ["blue sky"]
        ui = load_functions(
            "webui/Main.py", {"_render_local_script_generation"},
            dict(self.namespace, hashlib=hashlib, _run_llm_read_operation=lambda name, call: call({})),
        )
        for enabled in (False, True):
            ui._render_local_script_generation(self.schema.VideoParams(
                video_subject="Céu", rick_profile_enabled=enabled,
            ))
            self.assertEqual(llm.generate_script.call_args.kwargs.get("rick_profile_enabled", False), enabled)
            if not enabled:
                self.assertNotIn("rick_profile_enabled", llm.generate_script.call_args.kwargs)

    def test_invalid_generated_script_does_not_spend_on_keywords_or_replace_manual_text(self):
        self.st.button.return_value = True
        llm = self.namespace["llm"]
        llm.generate_script.return_value = ""
        original = self.st.session_state["video_script"]
        ui = load_functions(
            "webui/Main.py", {"_render_local_script_generation"},
            dict(self.namespace, _run_llm_read_operation=lambda name, call: call({})),
        )
        ui._render_local_script_generation(self.schema.VideoParams(
            video_subject="Céu", rick_profile_enabled=True,
        ))
        llm.generate_script.assert_called_once()
        llm.generate_terms.assert_not_called()
        self.assertEqual(self.st.session_state["video_script"], original)
        self.st.error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
