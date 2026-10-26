"""One-time, non-secret WebUI startup preferences for the Rick project.

This module deliberately has no configuration or Streamlit dependencies, so it
can be tested offline. The WebUI applies the preset once, then persists the
version marker; later user changes are saved by the existing controls.
"""

from __future__ import annotations

from typing import Mapping


PRESET_VERSION = 1
PRESET_MARKER = "rick_startup_preset_version"

# Never put credentials, API keys, prompts or user-generated content here.
RICK_STARTUP_DEFAULTS = {
    "ui": {
        "rick_profile_enabled": True,
        "avoid_repeated_materials": True,
        "video_language": "pt-BR",
        "video_concat_mode": "sequential",
        "video_transition_mode": None,
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
    if ui_config.get(PRESET_MARKER) == PRESET_VERSION:
        return ()
    return tuple(
        (section, name, value)
        for section, defaults in RICK_STARTUP_DEFAULTS.items()
        for name, value in defaults.items()
    )
