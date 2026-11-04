"""Rick 02F: bounded targeted searching and re-assessment; no auto approval.

Tests are fully offline and cannot access external Gemini/Pexels/Pixabay.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from app.services import rick_semantic_remediation as remed


def _scenes():
    return [
        {"text": "Gramsci estudou como ideias dominam"},
        {"text": "A sociedade e o parlamento discutem leis"},
        {"text": "O grupo muda isso sem"},
        {"text": "precisar de revoluções violentas."},
    ]


def _proposals():
    return {
        "scenes": [
            {
                "scene_number": i, "text": scene["text"],
                "primary": f"wrong{i}.mp4", "metadata_score": 80,
            }
            for i, scene in enumerate(_scenes(), 1)
        ],
    }


def _assessments():
    return {
        "version": 2, "model": "gemini-test",
        "results": [
            {
                "scene_number": 1, "file": "wrong1.mp4",
                "status": "ai_assessment_for_human_review",
                "verdict": "plausible", "visual_relation": "direct",
            },
            {
                "scene_number": 2, "file": "wrong2.mp4",
                "status": "ai_assessment_for_human_review",
                "verdict": "uncertain", "visual_relation": "unrelated",
            },
            {
                "scene_number": 3, "file": "wrong3.mp4",
                "status": "ai_assessment_for_human_review",
                "verdict": "uncertain", "visual_relation": "insufficient",
            },
            {
                "scene_number": 4, "file": "wrong4.mp4",
                "status": "ai_assessment_for_human_review",
                "verdict": "uncertain", "visual_relation": "metaphorical",
            },
        ],
    }


def _workspace(tmp_path, approved=False):
    names = [f"wrong{i}.mp4" for i in range(1, 5)]
    names += ["parliament.mp4", "other_parliament.mp4"]
    paths = {}
    for name in names:
        path = tmp_path / name
        path.write_bytes(b"offline fake video")
        paths[name] = str(path)
    return {
        "paths": paths,
        "preview": {"scenes": _scenes()},
        "preview_sha256": "stable-mock-preview-fingerprint",
        "source_metadata": {
            "parliament.mp4": {
                "search_term": "parliament government institutions",
                "title": "Parliament government institutions",
                "asset_id": "pixabay:parliament",
                "source_page": "https://pixabay.com/videos/123",
            },
            "other_parliament.mp4": {
                "search_term": "parliament government institutions",
                "title": "Parliament government institutions",
                "asset_id": "pixabay:other",
                "source_page": "https://pixabay.com/videos/124",
            },
        },
        "saved_review": {
            "scenes": [
                {"editorial_review": "unreviewed"},
                {"editorial_review": "approved_by_human" if approved else "unreviewed"},
                {"editorial_review": "unreviewed"},
                {"editorial_review": "unreviewed"},
            ],
        },
    }


def test_problem_scenes_exclude_direct_and_human_approved(tmp_path):
    result = remed._problem_scenes(
        _assessments(), _proposals(), model="gemini-test",
        saved_review=_workspace(tmp_path, approved=True)["saved_review"],
        max_scenes=3,
    )
    assert result == [3, 4]


def test_stale_mismatched_candidate_is_not_retried():
    report = _assessments()
    report["results"][1]["file"] = "different.mp4"
    targets = remed._problem_scenes(
        report, _proposals(), model="gemini-test", saved_review=None,
        max_scenes=3,
    )
    assert targets == [3, 4]


def test_stale_model_or_version_is_blocked():
    with pytest.raises(ValueError, match="incompatível"):
        remed._problem_scenes(
            {**_assessments(), "version": 1}, _proposals(),
            model="gemini-test", saved_review=None, max_scenes=3,
        )
    with pytest.raises(ValueError, match="incompatível"):
        remed._problem_scenes(
            _assessments(), _proposals(),
            model="different", saved_review=None, max_scenes=3,
        )


def test_no_consent_means_no_disk_or_network_operation(monkeypatch):
    monkeypatch.setattr(
        remed, "load_review_workspace",
        lambda *args, **kwargs: pytest.fail("no file reads without consent"),
    )
    with pytest.raises(ValueError, match="consent_required"):
        remed.run_semantic_remediation(
            "/not-used", "task", [], original_proposals=_proposals(),
            semantic_assessment=_assessments(),
            subject="Gramsci", api_key="not-real", model="gemini-test",
            consent=False,
        )


def test_imports_for_only_flagged_scenes_and_rechecks_via_ai(
    monkeypatch, tmp_path,
):
    workspace = _workspace(tmp_path)
    captured = []
    calls = []
    monkeypatch.setattr(
        remed, "load_review_workspace", lambda *a, **kw: workspace,
    )
    from app.services import rick_scene_discovery

    def discover(*args, **kwargs):
        captured.append(kwargs)
        return {"imported_count": 1, "imported": []}

    monkeypatch.setattr(
        rick_scene_discovery, "discover_scene_media", discover,
    )

    def fake_review(report, paths, **kwargs):
        calls.append((report, paths, kwargs))
        target = next(
            r for r in report["scenes"] if r["primary"] is not None
        )
        return {
            "version": 2,
            "api_requests": 1,
            "assessed": 1,
            "results": [{
                "scene_number": target["scene_number"],
                "file": target["primary"],
                "status": "ai_assessment_for_human_review",
                "verdict": "uncertain",
                "visual_relation": "contextual",
                "visible_evidence": "Um prédio parlamentar",
                "reason": "O país e o período são desconhecidos",
            }],
        }

    monkeypatch.setattr(remed, "review_scene_frames", fake_review)
    before = deepcopy(_proposals())
    result = remed.run_semantic_remediation(
        tmp_path, "task", [],
        original_proposals=before,
        semantic_assessment=_assessments(),
        subject="Gramsci", api_key="not-real",
        model="gemini-test", consent=True,
        max_scenes=3,
    )
    assert captured[0]["priority_scene_numbers"] == [2, 3, 4]
    assert captured[0]["priority_only"] is True
    assert captured[0]["max_clips"] == 3
    assert captured[0]["max_stills"] == 4
    assert len(calls) == 1
    assert len(calls[0][0]["scenes"]) == 4
    assert calls[0][2]["max_scenes"] == 3
    assert calls[0][2]["consent"] is True
    assert result["compared"][0]["original_file"] == "wrong2.mp4"
    assert result["compared"][0]["selected_as_primary"] is False
    assert result["human_approved"] is False
    assert result["publishing_permitted"] is False
    assert before == _proposals()
    assert workspace["saved_review"]["scenes"][1]["editorial_review"] == "unreviewed"


def test_when_no_candidate_never_calls_gemini(
    monkeypatch, tmp_path,
):
    workspace = _workspace(tmp_path)
    workspace["source_metadata"] = {}
    monkeypatch.setattr(
        remed, "load_review_workspace", lambda *a, **kw: workspace,
    )
    monkeypatch.setattr(
        remed, "review_scene_frames",
        lambda *a, **kw: pytest.fail("No matching candidate, no paid call"),
    )
    result = remed.run_semantic_remediation(
        tmp_path, "task", [],
        original_proposals=_proposals(),
        semantic_assessment=_assessments(),
        subject="Gramsci", api_key="not-real",
        model="gemini-test", consent=True, discover=False,
    )
    assert result["api_requests"] == 0
    assert result["compared"] == []
    assert len(result["unresolved"]) == 3


def test_stale_script_blocks_before_discovery(monkeypatch, tmp_path):
    workspace = _workspace(tmp_path)
    workspace["preview"]["scenes"][0]["text"] = "Text edited after analysis"
    monkeypatch.setattr(
        remed, "load_review_workspace", lambda *a, **kw: workspace,
    )
    with pytest.raises(ValueError, match="desatualizada"):
        remed.run_semantic_remediation(
            tmp_path, "task", [],
            original_proposals=_proposals(),
            semantic_assessment=_assessments(),
            subject="Gramsci", api_key="not-real",
            model="gemini-test", consent=True,
        )


@pytest.mark.parametrize("limit", [0, 4, True, -1])
def test_rejects_unbounded_number_of_scenes(limit):
    with pytest.raises(ValueError, match="inválidos"):
        remed.run_semantic_remediation(
            ".", "task", [],
            original_proposals=_proposals(),
            semantic_assessment=_assessments(),
            subject="Gramsci", api_key="not-real", model="gemini-test",
            consent=True, max_scenes=limit,
        )


def test_ignores_approved_direct_matching_and_avoids_redundant_search(
    monkeypatch, tmp_path,
):
    workspace = _workspace(tmp_path)
    report = _assessments()
    for row in report["results"]:
        row["verdict"] = "plausible"
        row["visual_relation"] = "direct"
    monkeypatch.setattr(
        remed, "load_review_workspace", lambda *a, **kw: workspace,
    )
    from app.services import rick_scene_discovery
    monkeypatch.setattr(
        rick_scene_discovery, "discover_scene_media",
        lambda *a, **kw: pytest.fail("Do not rediscover direct matches"),
    )
    monkeypatch.setattr(
        remed, "review_scene_frames",
        lambda *a, **kw: pytest.fail("No Gemini calls"),
    )
    result = remed.run_semantic_remediation(
        tmp_path, "task", [], original_proposals=_proposals(),
        semantic_assessment=report, subject="Gramsci",
        api_key="not-real", model="gemini-test", consent=True,
    )
    assert result["targets"] == []
    assert result["api_requests"] == 0


def test_ui_contains_single_action_and_never_permits_publication():
    source = (Path(__file__).parents[2] / "webui" / "rick_editorial_panel.py").read_text(
        encoding="utf-8"
    )
    assert "Buscar alternativas e reavaliar até 3 cenas com IA" in source
    assert "run_semantic_remediation(" in source
    assert "disabled=not (authorized and key_ready and model_name)" in source
    assert "Nenhuma substituição ou aprovação foi realizada" in source
    assert 'st.session_state.pop(' in source
    assert 'f"rick_ai_fix_result_{selected_id}_{first_scene}"' in source


def test_strict_discovery_never_searches_other_scenes(monkeypatch):
    from app.services import rick_scene_discovery

    requests = []
    monkeypatch.setattr(
        rick_scene_discovery, "_stock_provider",
        lambda: ("pixabay", lambda query, *_: requests.append(query) or []),
    )
    spoken = [
        {"text": "Um parlamento reuniu os deputados"},
        {"text": "As eleições ocorreram por votação em urna"},
        {"text": "Manifestantes protestaram na rua"},
    ]
    result = rick_scene_discovery.discover_scene_media(
        "/not-used", "task", subject="política",
        scenes=spoken, source_metadata={}, max_stills=0,
        max_clips=2, priority_scene_numbers=[2], priority_only=True,
    )
    assert requests == ["elections voting ballot people"]
    assert result["priority_scene_numbers"] == [2]
    assert result["imported_count"] == 0


def test_strict_discovery_with_empty_priority_makes_no_requests(monkeypatch):
    from app.services import rick_scene_discovery

    monkeypatch.setattr(
        rick_scene_discovery, "_stock_provider",
        lambda: ("pixabay", lambda *a: pytest.fail("Should not search")),
    )
    result = rick_scene_discovery.discover_scene_media(
        "/not-used", "task", subject="política",
        scenes=[{"text": "As eleições ocorreram"}],
        source_metadata={}, max_stills=0, max_clips=2,
        priority_scene_numbers=[], priority_only=True,
    )
    assert result["search_requests"] == 0


def test_legacy_discovery_behavior_remains_explicitly_non_strict(monkeypatch):
    from app.services import rick_scene_discovery

    requests = []
    monkeypatch.setattr(
        rick_scene_discovery, "_stock_provider",
        lambda: ("pixabay", lambda query, *_: requests.append(query) or []),
    )
    rick_scene_discovery.discover_scene_media(
        "/not-used", "task", subject="política",
        scenes=[
            {"text": "Parlamento com representantes"},
            {"text": "As eleições ocorreram"},
        ],
        source_metadata={}, max_stills=0, max_clips=2,
        priority_scene_numbers=[2],
    )
    assert "elections voting ballot people" in requests
    assert "parliament government institutions" in requests
