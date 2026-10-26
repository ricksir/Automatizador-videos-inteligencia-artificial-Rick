"""Rick script integration with fake configuration, transport mocks and no APIs."""

import types
import unittest
from unittest.mock import Mock, patch

from app.services import rick_quality
from test.services.rick_test_support import load_functions, load_module, offline_context


class TestRickScripts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.isolation = offline_context()
        cls.addClassCleanup(cls.isolation.close)
        cls.llm = load_module("app/services/llm.py", "_rick_test_llm")
        cls.schema = load_module("app/models/schema.py", "_rick_test_schema")

    def test_profile_defaults_off_in_both_models(self):
        self.assertFalse(self.schema.VideoParams(video_subject="Céu").rick_profile_enabled)
        self.assertFalse(self.schema.VideoScriptRequest().rick_profile_enabled)

    def test_disabled_prompt_matches_original(self):
        prompt = self.llm.build_script_prompt("Céu", language="pt-BR")
        expected = (
            self.llm.DEFAULT_SCRIPT_SYSTEM_PROMPT
            + "\n\n# Initialization:\n- video subject: Céu\n- number of paragraphs: 1"
            + "\n- language: pt-BR"
        )
        self.assertEqual(prompt, expected)
        self.assertEqual(prompt, self.llm.build_script_prompt("Céu", "pt-BR", rick_profile_enabled=False))

    def test_active_profile_prioritizes_brazilian_language_and_honest_hook(self):
        prompt = self.llm.build_script_prompt(
            "Why is the sky blue?", language="en-US", custom_system_prompt="Write in English.",
            rick_profile_enabled=True,
        )
        self.assertIn("- language: pt-BR", prompt)
        self.assertNotIn("- language: en-US", prompt)
        self.assertTrue(prompt.endswith(rick_quality.SCRIPT_INSTRUCTIONS))
        self.assertIn("Não invente fatos", prompt)
        self.assertIn("promessas enganosas", prompt)
        self.assertIn("3 segundos", prompt)
        self.assertIn("35 a 50 segundos", prompt)

    def test_provider_adapter_receives_profile_without_config_changes(self):
        snapshot = {"llm_provider": "groq", "model": "fake-offline"}
        before = dict(snapshot)
        text = "Você sabia? Dá pra explicar por que o céu é azul!"
        with patch.object(self.llm, "_generate_response", return_value=text) as provider:
            result = self.llm.generate_script("Céu", app_config=snapshot, rick_profile_enabled=True)
        self.assertEqual(result, text)
        provider.assert_called_once()
        self.assertIs(provider.call_args.kwargs["app_config"], snapshot)
        self.assertEqual(snapshot, before)

    def test_active_invalid_responses_do_not_regenerate(self):
        for response in ("", None, [], {"script": "Olá"}, '{"script":"Olá"}', "...", "Error: indisponível"):
            with self.subTest(response=response):
                with patch.object(self.llm, "_generate_response", return_value=response) as provider:
                    self.assertEqual(self.llm.generate_script("Céu", rick_profile_enabled=True), "")
                provider.assert_called_once()

    def test_active_short_and_long_estimates_do_not_regenerate(self):
        for text in ("O céu é azul.", "curiosidade " * 200):
            with self.subTest(length=len(text)):
                with patch.object(self.llm, "_generate_response", return_value=text) as provider:
                    self.assertEqual(
                        self.llm.generate_script("Céu", rick_profile_enabled=True), text.strip(),
                    )
                provider.assert_called_once()

    def test_active_provider_exception_does_not_regenerate(self):
        with patch.object(self.llm, "_generate_response", side_effect=RuntimeError("offline")) as provider:
            self.assertEqual(self.llm.generate_script("Céu", rick_profile_enabled=True), "")
        provider.assert_called_once()

    def test_original_retry_behavior_is_preserved_when_disabled(self):
        with patch.object(self.llm, "_generate_response", side_effect=["", "Texto original."]) as provider:
            self.assertEqual(self.llm.generate_script("Céu"), "Texto original.")
        self.assertEqual(provider.call_count, 2)

    def test_manual_script_never_calls_llm(self):
        llm = Mock()
        task = load_functions("app/services/task.py", {"generate_script"}, {"llm": llm, "logger": Mock()})
        for enabled in (False, True):
            text = "Você sabia? Pois é, dá pra entender o céu!"
            params = self.schema.VideoParams(video_subject="Céu", video_script=text, rick_profile_enabled=enabled)
            self.assertEqual(task.generate_script("offline", params), text)
        llm.generate_script.assert_not_called()

    def test_task_passes_profile_only_when_enabled(self):
        llm = Mock()
        llm.generate_script.return_value = "Texto brasileiro."
        task = load_functions("app/services/task.py", {"generate_script"}, {"llm": llm, "logger": Mock()})
        for enabled in (False, True):
            task.generate_script("offline", self.schema.VideoParams(video_subject="Céu", rick_profile_enabled=enabled))
            self.assertEqual(llm.generate_script.call_args.kwargs.get("rick_profile_enabled", False), enabled)
            if not enabled:
                self.assertNotIn("rick_profile_enabled", llm.generate_script.call_args.kwargs)

    def test_api_forwards_optional_profile(self):
        llm = Mock()
        llm.generate_script.return_value = "Roteiro brasileiro."
        controller = load_functions(
            "app/controllers/v1/llm.py", {"generate_video_script"},
            {"llm": llm, "utils": types.SimpleNamespace(get_response=lambda status, data: data)},
        )
        for enabled in (False, True):
            response = controller.generate_video_script(None, self.schema.VideoScriptRequest(rick_profile_enabled=enabled))
            self.assertEqual(response["video_script"], "Roteiro brasileiro.")
            self.assertEqual(llm.generate_script.call_args.kwargs.get("rick_profile_enabled", False), enabled)


if __name__ == "__main__":
    unittest.main()
