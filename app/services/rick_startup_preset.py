"""One-time, non-secret WebUI startup preferences for the Rick project.

This module deliberately has no configuration or Streamlit dependencies, so it
can be tested offline. The WebUI applies the preset once, then seeds the widget
session state before rendering. Later user changes are saved normally.
"""

from __future__ import annotations

from typing import Mapping


PRESET_VERSION = 2
PRESET_MARKER = "rick_startup_preset_version"

# Never put credentials, API keys, prompts or user-generated content here.
RICK_STARTUP_DEFAULTS = {
    "ui": {
        "rick_profile_enabled": True,
        "avoid_repeated_materials": True,
        "video_language": "pt-BR",
        "video_concat_mode": "sequential",
        "video_aspect_pixabay": "9:16",
        "video_fit_mode": "cover",
        "video_clip_duration": 4,
        "video_clip_speed": 1.0,
        "video_count": 1,
        "voice_mode": "tts",
        "tts_server": "gemini-tts",
        "voice_name": "gemini:Charon-Informative",
        "voice_volume": 1.0,
        "voice_rate": 1.0,
        "bgm_type": "",
        "subtitle_enabled": True,
        "font_name": "BeVietnamPro-Bold.ttf",
        "subtitle_position": "bottom",
        "subtitle_display_mode": "sentence",
        "subtitle_animation": "none",
        "text_fore_color": "#FFFFFF",
        "font_size": 55,
        "stroke_color": "#000000",
        "stroke_width": 1.5,
        "subtitle_background_enabled": False,
        "rounded_subtitle_background": False,
    },
    "app": {
        "video_source": "pixabay",
        "match_materials_to_script": True,
        "upload_post_enabled": False,
        "upload_post_auto_upload": False,
    },
}


def pending_startup_settings(ui_config: Mapping) -> tuple[tuple[str, str, object], ...]:
    """Return the first-run preference writes, or none once already applied."""
    # Version 1 saved the settings but did not initialize Streamlit widgets,
    # allowing stale browser/session values to overwrite them on first load.
    # Version 2 explicitly fixes this by reseeding the widgets once.
    if ui_config.get(PRESET_MARKER) == PRESET_VERSION:
        return ()
    return tuple(
        (section, name, value)
        for section, defaults in RICK_STARTUP_DEFAULTS.items()
        for name, value in defaults.items()
    )


def seed_startup_widgets(session_state, set_widget):
    """Synchronize an existing/replayed Streamlit session on first application.

    Called only once when the preset version is upgraded, before rendering any
    widget. The caller maps logical widget names to localized widget keys.
    """
    session_state.update({
        "rick_profile_enabled": True,
        "avoid_repeated_materials": True,
        "match_materials_to_script": True,
        "subtitle_enabled_checkbox": True,
        "font_color_picker": "#FFFFFF",
        "font_size_slider": 55,
        "stroke_color_picker": "#000000",
        "stroke_width_slider": 1.5,
        "subtitle_background_enabled_checkbox": False,
        "rounded_subtitle_background_checkbox": False,
    })
    session_state.pop("rick_previous_script_language", None)
    for widget, value in (
        ("script_language_select", "pt-BR"),
        ("video_source_select", "pixabay"),
        ("video_concat_mode_select", "sequential"),
        ("video_aspect_for_pixabay", "9:16"),
        ("video_fit_mode_select", "cover"),
        ("video_clip_duration_select", 4),
        ("video_clip_speed_slider", 1.0),
        ("video_count_select", 1),
        ("voice_mode_control", "tts"),
        ("tts_server_select", "gemini-tts"),
        ("speech_synthesis_select_gemini-tts", "gemini:Charon-Informative"),
        ("voice_volume_select", 1.0),
        ("voice_rate_select", 1.0),
        ("bgm_type_select", ""),
        ("font_name_select", "BeVietnamPro-Bold.ttf"),
        ("subtitle_position_select", "bottom"),
        ("subtitle_display_mode_select", "sentence"),
        ("subtitle_animation_select", "none"),
        ("video_transition_mode_select", None),
    ):
        set_widget(widget, value)
