"""Ranking of semantically checked alternatives is conservative and bounded.

No network, provider keys, approval state, video editing or publishing.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from app.services import rick_semantic_candidate_ranker as ranking
from app.services import rick_semantic_remediation as remed


def _candidate(scene, file, *, verdict="uncertain", relation="contextual", score=95):
    return {
        "scene_number": scene,
        "file": file,
        "status": "ai_assessment_for_human_review",
        "verdict": verdict,
        "visual_relation": relation,
        "visible_evidence": "Uma discussão visível",
        "reason": "A imagem representa uma discussão",
        "metadata_score": score,
    }


def test_high_metadata_score_never_becomes_visual_match():
    results = ranking.rank_semantic_alternatives([
        _candidate(1, "metadata99.mp4", score=99),
        _candidate(1, "metaphor.mp4", verdict="uncertain",
                   relation="metaphorical", score=99),
    ], [1])
    assert results[0]["suggested_file"] is None
    assert results[0]["status"] == "sem_correspondencia_direta_demonstrada"
    assert not results[0]["publishing_permitted"]
    assert not results[0]["auto_selection_permitted"]


def test_only_direct_plausible_becomes_human_review_lead():
    results = ranking.rank_semantic_alternatives([
        _candidate(2, "a.mp4", verdict="plausible",
                   relation="direct", score=52),
        _candidate(2, "b.mp4", verdict="uncertain",
                   relation="contextual", score=99),
    ], [2])
    assert results[0]["suggested_file"] == "a.mp4"
    assert results[0]["direct_candidates"] == 1
    assert results[0]["human_approved"] is False
    assert results[0]["license_verified"] is False
    assert results[0]["auto_selection_permitted"] is False


def test_invalid_and_empty_evidence_never_win():
    invalid = _candidate(1, "bad.mp4", verdict="plausible",
                         relation="direct", score=99)
    invalid["status"] = "provider_or_response_failure"
    empty = _candidate(1, "empty.mp4", verdict="plausible",
                       relation="direct", score=99)
    empty["visible_evidence"] = " "
    assert ranking.rank_semantic_alternatives(
        [invalid, empty], [1]
    )[0]["suggested_file"] is None


def test_a_direct_tie_is_deterministic_without_claiming_confidence():
    outcomes = ranking.rank_semantic_alternatives([
        _candidate(1, "z.mp4", verdict="plausible", relation="direct", score=75),
        _candidate(1, "a.mp4", verdict="plausible", relation="direct", score=75),
    ], [1])
    assert outcomes[0]["suggested_file"] == "a.mp4"
    assert outcomes[0]["direct_candidates"] == 2


def _fixtures(tmp_path, scenes=1):
    texts = [
        "A sociedade pode discutir ideias",
        "O grupo pode mudar isso sem",
        "precisar de revoluções violentas.",
    ][:scenes]
    paths = {}
    meta = {}
    for i in range(1, scenes + 1):
        for prefix in ["original", "alternative1", "alternative2"]:
            name = f"{prefix}-{i}.mp4"
            path = tmp_path / name
            path.write_bytes(b"fake media")
            paths[name] = str(path)
            if prefix != "original":
                meta[name] = {
                    "title": "A sociedade pode discutir ideias",
                    "search_term": "people discussing ideas books",
                    "source_page": f"https://pixabay.com/videos/{i}",
                }
    original = {"scenes": [
        {"scene_number": i, "text": t,
         "primary": f"original-{i}.mp4", "metadata_score": 90}
        for i, t in enumerate(texts, 1)
    ]}
    assessment = {
        "version": 2, "model": "fake-gemini", "results": [
            {"scene_number": i, "file": f"original-{i}.mp4",
             "status": "ai_assessment_for_human_review",
             "verdict": "uncertain", "visual_relation": "contextual"}
            for i in range(1, scenes + 1)
        ],
    }
    workspace = {
        "paths": paths,
        "preview": {"scenes": [{"text": t} for t in texts]},
        "source_metadata": meta,
        "saved_review": {"scenes": [
            {"editorial_review": "unreviewed"} for _ in texts
        ]},
    }
    return workspace, original, assessment


def _run(monkeypatch, tmp_path, *, n=1, first_relation="contextual",
         second_relation="direct", max_candidates=2):
    workspace, original, assessments = _fixtures(tmp_path, n)
    monkeypatch.setattr(
        remed, "load_review_workspace", lambda *args, **kwargs: workspace,
    )
    def fake_score(scene, intent, name, meta):
        score = 75 if "alternative1" in name else 60
        return {"name": name, "score": score}
    monkeypatch.setattr(remed, "_score", fake_score)
    seen = []
    def fake_gemini(report, paths, **kwargs):
        selected = [r for r in report["scenes"] if r["primary"] is not None]
        seen.append(selected)
        rows = []
        for r in selected:
            is_second = "alternative2" in r["primary"]
            relation = second_relation if is_second else first_relation
            rows.append({
                "scene_number": r["scene_number"],
                "file": r["primary"],
                "status": "ai_assessment_for_human_review",
                "verdict": "plausible" if relation == "direct" else "uncertain",
                "visual_relation": relation,
                "visible_evidence": "Pessoas discutindo livros",
                "reason": "Há uma reunião visível",
            })
        return {
            "version": 2, "assessed": len(rows),
            "api_requests": len(rows), "results": rows,
        }
    monkeypatch.setattr(remed, "review_scene_frames", fake_gemini)
    snapshot = deepcopy(original)
    result = remed.run_semantic_remediation(
        tmp_path, "task", [], original_proposals=original,
        semantic_assessment=assessments, subject="Gramsci",
        api_key="fake-key", model="fake-gemini", consent=True,
        discover=False, max_scenes=n,
        max_candidates_per_scene=max_candidates,
    )
    assert original == snapshot
    assert all(
        r["editorial_review"] == "unreviewed"
        for r in workspace["saved_review"]["scenes"]
    )
    assert result["original_proposals_unchanged"] is True
    assert result["human_approved"] is False
    assert result["publishing_permitted"] is False
    assert all(
        row["selected_as_primary"] is False
        and row["rights_verified"] is False
        for row in result["compared"]
    )
    return result, seen


def test_two_candidate_rounds_find_direct_match_without_replacing(monkeypatch, tmp_path):
    result, seen = _run(monkeypatch, tmp_path, n=2)
    assert len(seen) == 2
    assert result["api_requests"] == 4
    assert result["ai_assessed"] == 4
    assert len(result["compared"]) == 4
    assert all(row["candidate_order"] in {1, 2} for row in result["compared"])
    assert all(row["suggested_file"].startswith("alternative2-")
               for row in result["ranking"])
    assert len(set(r["file"] for r in result["compared"])) == 4


def test_stops_when_first_candidate_is_direct(monkeypatch, tmp_path):
    result, seen = _run(monkeypatch, tmp_path, first_relation="direct")
    assert len(seen) == 1
    assert result["api_requests"] == 1
    assert len(result["compared"]) == 1
    assert result["ranking"][0]["suggested_file"].startswith("alternative1")


def test_two_weak_alternatives_do_not_produce_a_winner(monkeypatch, tmp_path):
    result, seen = _run(
        monkeypatch, tmp_path, first_relation="contextual",
        second_relation="metaphorical",
    )
    assert len(seen) == 2
    assert result["ranking"][0]["suggested_file"] is None
    assert result["ranking"][0]["direct_candidates"] == 0


def test_only_one_candidate_mode_preserves_prior_limit(monkeypatch, tmp_path):
    result, seen = _run(
        monkeypatch, tmp_path, n=2, max_candidates=1,
    )
    assert len(seen) == 1
    assert result["api_requests"] == 2
    assert all(row["candidate_order"] == 1 for row in result["compared"])


def test_six_requests_max_and_no_implicit_pub(monkeypatch, tmp_path):
    result, seen = _run(monkeypatch, tmp_path, n=3)
    assert result["api_requests"] == 6
    assert len(seen) == 2
    assert len(result["ranking"]) == 3
    assert all(row["human_approved"] is False
               for row in result["ranking"])


@pytest.mark.parametrize("value", [0, 3, True, -1, "2"])
def test_cannot_exceed_candidate_cap_even_with_consent(tmp_path, value):
    _, original, assessments = _fixtures(tmp_path)
    with pytest.raises(ValueError, match="inválidos"):
        remed.run_semantic_remediation(
            tmp_path, "task", [], original_proposals=original,
            semantic_assessment=assessments, subject="Gramsci",
            api_key="fake-key", model="fake-gemini", consent=True,
            max_candidates_per_scene=value,
        )


def test_screen_explains_cost_and_cannot_auto_approve():
    source = (
        Path(__file__).parents[2] / "webui" / "rick_editorial_panel.py"
    ).read_text(encoding="utf-8")
    assert "Máximo de alternativas por cena" in source
    assert "Comparação semântica — indicação para revisão humana" in source
    assert "O arquivo atual continua selecionado." in source
    assert "max_candidates_per_scene=alternatives_per_scene" in source
