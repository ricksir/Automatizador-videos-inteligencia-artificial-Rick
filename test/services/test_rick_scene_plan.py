"""Offline tests for estimated Rick visual scene planning."""

import json
import math

import pytest

from app.services.rick_scene_plan import build_scene_plan


SCRIPT = (
    "Antonio Gramsci escreveu sobre a disputa de ideias na sociedade. "
    "Grupos organizados procuram convencer pessoas e construir consensos. "
    "No Brasil, as campanhas eleitorais usam discursos e redes sociais. "
    "O debate público envolve diferentes argumentos e projetos políticos. "
    "Nenhuma fotografia de uma pessoa está garantida por uma busca em bancos de vídeos."
)


def test_video_of_45_seconds_is_partitioned_into_ordered_contiguous_scenes():
    terms = ["books library", "political rally", "election Brazil", "debate"]
    plan = build_scene_plan(SCRIPT, terms, 45.0, target_clip_seconds=4)
    assert plan["scene_count"] == math.ceil(45 / 4)
    assert plan["scenes"][0]["start_seconds"] == 0
    assert plan["scenes"][-1]["end_seconds"] == 45.0
    assert all(
        a["end_seconds"] == b["start_seconds"]
        for a, b in zip(plan["scenes"], plan["scenes"][1:])
    )
    assert all(scene["start_seconds"] < scene["end_seconds"] for scene in plan["scenes"])
    assert plan["alignment"] == "estimated"
    assert all(scene["media_verified"] is False for scene in plan["scenes"])
    assert json.loads(json.dumps(plan)) == plan


def test_no_script_words_lost_and_accents_are_preserved():
    plan = build_scene_plan(SCRIPT, ["books", "debate"], 35)
    assert " ".join(scene["text"] for scene in plan["scenes"]) == " ".join(SCRIPT.split())
    assert "políticos" in plan["scenes"][-1]["text"] or "políticos" in SCRIPT
    assert "Gramsci" in plan["scenes"][0]["text"]


@pytest.mark.parametrize("duration", [35.0, 50.0, 47.3726])
def test_critical_durations(duration):
    plan = build_scene_plan(SCRIPT, ["books", "speech"], duration)
    assert plan["scenes"][-1]["end_seconds"] == duration
    assert sum(
        (scene["end_seconds"] - scene["start_seconds"]) for scene in plan["scenes"]
    ) == pytest.approx(duration)


def test_search_terms_are_ordered_and_not_semantically_certified():
    terms = ["Gramsci portrait", "library books", "political rally Brazil"]
    plan = build_scene_plan(SCRIPT, terms, 45)
    indices = [terms.index(scene["search_term"]) for scene in plan["scenes"]]
    assert indices == sorted(indices)
    assert any(w["code"] == "scene_terms_reused" for w in plan["warnings"])
    assert plan["source_media_verified"] is False


def test_empty_terms_return_preview_with_warning_but_do_not_fake_media():
    plan = build_scene_plan("Curiosidade científica do céu.", [], 4)
    assert len(plan["scenes"]) == 1
    assert plan["scenes"][0]["search_term"] is None
    assert any(w["code"] == "scene_search_terms_missing" for w in plan["warnings"])


def test_short_script_does_not_create_empty_scenes():
    plan = build_scene_plan("Céu azul", ["blue sky"], 45)
    assert plan["scene_count"] == 2
    assert all(scene["text"] for scene in plan["scenes"])


@pytest.mark.parametrize(
    "script,terms,seconds,target",
    [
        ("", [], 30, 4),
        ("  \n ", [], 30, 4),
        (None, [], 30, 4),
        ("texto", [], 0, 4),
        ("texto", [], -1, 4),
        ("texto", [], float("nan"), 4),
        ("texto", [], float("inf"), 4),
        ("texto", [], 30, 0),
        ("texto", [], 30, float("inf")),
        ("texto", "stock image", 30, 4),
        ("texto", [123], 30, 4),
    ],
)
def test_invalid_input_is_rejected(script, terms, seconds, target):
    with pytest.raises(ValueError):
        build_scene_plan(script, terms, seconds, target_clip_seconds=target)


def test_long_script_and_many_terms_have_strict_bounded_scene_count():
    script = " ".join(["Ciência e história são interessantes."] * 500)
    terms = [f"term {i}" for i in range(100)]
    plan = build_scene_plan(script, terms, 1000, target_clip_seconds=2)
    assert plan["scene_count"] <= 60
    assert plan["scenes"][-1]["end_seconds"] == 1000


def test_search_terms_deduplicated_and_blanks_ignored():
    plan = build_scene_plan("Céu azul e belíssimo.", ["blue sky", "", " blue sky ", "sky"], 8)
    assert {x["search_term"] for x in plan["scenes"]} <= {"blue sky", "sky"}


def test_slow_rhythm_can_produce_one_scene_without_search_terms():
    plan = build_scene_plan("A luz.", [], 1.3, target_clip_seconds=4)
    assert plan["scene_count"] == 1
    assert plan["scenes"][0]["end_seconds"] == 1.3
