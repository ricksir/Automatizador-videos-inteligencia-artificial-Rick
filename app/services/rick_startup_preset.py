"""One-time, non-secret WebUI startup preferences for the Rick project.

This module deliberately has no configuration or Streamlit dependencies, so it
can be tested offline. The WebUI applies the preset once and hydrates each Streamlit session from
saved preferences before rendering. Later user changes are saved normally.
"""

from __future__ import annotations

from typing import Mapping


PRESET_VERSION = 3
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
    # Version 3 fixes this by hydrating each new Streamlit session from config.
    if ui_config.get(PRESET_MARKER) == PRESET_VERSION:
        return ()
    return tuple(
        (section, name, value)
        for section, defaults in RICK_STARTUP_DEFAULTS.items()
        for name, value in defaults.items()
    )


def seed_startup_widgets(session_state, set_widget, *, ui_config=None, app_config=None):
    """Hydrate one Streamlit session from durable, whitelisted preferences.

    An upgrade writes the Rick defaults first. On *subsequent* page sessions,
    read saved choices instead of using the preset defaults, so user changes
    remain effective after closing and reopening the app. This function must
    run before rendering any controls and only once per Streamlit session.
    """
    ui = dict(RICK_STARTUP_DEFAULTS["ui"])
    app = dict(RICK_STARTUP_DEFAULTS["app"])
    if ui_config is not None:
        ui.update({key: ui_config[key] for key in ui if key in ui_config})
    if app_config is not None:
        app.update({key: app_config[key] for key in app if key in app_config})

    session_state.update({
        "rick_profile_enabled": bool(ui["rick_profile_enabled"]),
        "avoid_repeated_materials": bool(ui["avoid_repeated_materials"]),
        "match_materials_to_script": bool(app["match_materials_to_script"]),
        "subtitle_enabled_checkbox": bool(ui["subtitle_enabled"]),
        "font_color_picker": str(ui["text_fore_color"]),
        "font_size_slider": int(ui["font_size"]),
        "stroke_color_picker": str(ui["stroke_color"]),
        "stroke_width_slider": float(ui["stroke_width"]),
        "subtitle_background_enabled_checkbox": bool(ui["subtitle_background_enabled"]),
        "rounded_subtitle_background_checkbox": bool(ui["rounded_subtitle_background"]),
    })
    session_state.pop("rick_previous_script_language", None)
    tts_server = ui["tts_server"]
    video_source = app["video_source"]
    selections = (
        ("script_language_select", ui["video_language"]),
        ("video_source_select", video_source),
        ("video_concat_mode_select", ui["video_concat_mode"]),
        (f"video_aspect_for_{video_source}",
         (ui_config or {}).get(
             f"video_aspect_{video_source}", ui["video_aspect_pixabay"]
         )),
        ("video_fit_mode_select", ui["video_fit_mode"]),
        ("video_clip_duration_select", ui["video_clip_duration"]),
        ("video_clip_speed_slider", ui["video_clip_speed"]),
        ("video_count_select", ui["video_count"]),
        ("voice_mode_control", ui["voice_mode"]),
        ("tts_server_select", tts_server),
        (f"speech_synthesis_select_{tts_server}", ui["voice_name"]),
        ("voice_volume_select", ui["voice_volume"]),
        ("voice_rate_select", ui["voice_rate"]),
        ("bgm_type_select", ui["bgm_type"]),
        ("font_name_select", ui["font_name"]),
        ("subtitle_position_select", ui["subtitle_position"]),
        ("subtitle_display_mode_select", ui["subtitle_display_mode"]),
        ("subtitle_animation_select", ui["subtitle_animation"]),
    )
    for widget, value in selections:
        set_widget(widget, value)

    # The selected audio and video providers also have backend config values.
    # No credentials, tasks, topic/script content or API keys are touched.
