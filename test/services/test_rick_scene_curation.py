"""Offline unit tests for manual editorial review; no web, AI, or FFmpeg."""

from copy import deepcopy

import pytest

from app.services.rick_scene_curation import (
    apply_review,
    make_review,
    plan_fingerprint,
    render_review_html,
)


def _preview():
    return {
        "version": 1,
        "scene_count": 2,
        "status": "preview_only_not_rendered",
        "scenes": [
            {
                "number": 1,
                "start_seconds": 0,
                "end_seconds": 3,
                "text": "O filósofo Gramsci escreveu sobre hegemonia.",
                "search_term": "Antonio Gramsci portrait",
                "assigned_material_file": None,
                "match_status": "missing_term_match",
                "media_verified": False,
            },
            {
                "number": 2,
                "start_seconds": 3,
                "end_seconds": 6,
                "text": "A teoria discute disputa de ideias.",
                "search_term": "political ideas",
                "assigned_material_file": "old.mp4",
                "match_status": "term_match_unverified",
                "media_verified": False,
            },
        ],
        "warnings": [],
    }


def _approved(preview):
    rev = make_review(preview)
    rev["scenes"][0].update({
        "approved": True,
        "file": "rick-review-s1-portrait.mp4",
        "source_url": "https://acervo.example/gramsci",
        "credit": "Acervo de teste",
        "license": "Licença avaliada pelo editor",
    })
    rev["scenes"][1]["approved"] = True
    return rev


def test_new_review_is_pending_even_if_stock_file_exists():
    preview = _preview()
    review = make_review(preview)
    assert review["scenes"][0]["approved"] is False
    assert review["scenes"][1]["approved"] is False
    report = apply_review(preview, review, ["old.mp4"])
    assert report["status"] == "blocked"
    assert report["approved_preview"] is None


def test_curated_portrait_replaces_missing_stock_only_after_explicit_approval():
    preview = _preview()
    original = deepcopy(preview)
    review = _approved(preview)
    out = apply_review(preview, review, ["rick-review-s1-portrait.mp4", "old.mp4"])
    assert out["status"] == "approved"
    assert not out["blockers"]
    approved = out["approved_preview"]
    assert approved["scenes"][0]["assigned_material_file"] == "rick-review-s1-portrait.mp4"
    assert approved["scenes"][0]["match_status"] == "term_match_unverified"
    assert approved["scenes"][0]["editor_approved"] is True
    assert approved["scenes"][0]["editor_replaced_material"] is True
    assert approved["scenes"][0]["media_verified"] is False
    assert approved["source_media_verified"] is False
    assert approved["scenes"][1]["assigned_material_file"] == "old.mp4"
    assert preview == original


def test_missing_source_reference_blocks_new_photo():
    rev = _approved(_preview())
    rev["scenes"][0]["license"] = ""
    out = apply_review(_preview(), rev, ["rick-review-s1-portrait.mp4", "old.mp4"])
    assert out["status"] == "blocked"
    assert any(p["code"] == "replacement_provenance_missing" for p in out["blockers"])


@pytest.mark.parametrize("filename", [
    "../photo.mp4", r"C:\photos\photo.mp4", "/etc/passwd", "photo.jpg",
    "bad\\path.mp4", "a\x00.mp4", "..", "",
])
def test_manifest_path_injection_and_still_images_cannot_be_used_as_video(filename):
    rev = _approved(_preview())
    rev["scenes"][0]["file"] = filename
    out = apply_review(_preview(), rev, [filename, "old.mp4"])
    assert out["status"] == "blocked"
    assert out["approved_preview"] is None


def test_duplicate_file_names_from_multiple_directories_rejected():
    rev = _approved(_preview())
    out = apply_review(_preview(), rev, [
        "C:/dir1/rick-review-s1-portrait.mp4",
        "C:/dir2/rick-review-s1-portrait.mp4",
        "old.mp4",
    ])
    assert out["status"] == "blocked"
    assert any(x["code"] == "review_asset_unavailable" for x in out["blockers"])


def test_review_fingerprint_changes_with_narration():
    preview = _preview()
    old = make_review(preview)
    preview["scenes"][0]["text"] = "Texto foi alterado."
    assert plan_fingerprint(preview) != old["plan_fingerprint"]
    with pytest.raises(ValueError, match="desatualizada"):
        apply_review(preview, old, ["old.mp4"])


def test_missing_approval_or_missing_video_never_has_accepted_preview():
    rev = _approved(_preview())
    rev["scenes"][1]["approved"] = False
    assert apply_review(_preview(), rev, ["rick-review-s1-portrait.mp4"])["approved_preview"] is None


@pytest.mark.parametrize("field", ["source_url", "credit", "license"])
def test_bad_provenance_types_rejected(field):
    rev = _approved(_preview())
    rev["scenes"][0][field] = {"secret": 1}
    with pytest.raises(ValueError, match="inválido"):
        apply_review(_preview(), rev, ["rick-review-s1-portrait.mp4", "old.mp4"])


def test_source_url_must_not_be_javascript():
    rev = _approved(_preview())
    rev["scenes"][0]["source_url"] = "javascript:alert(1)"
    out = apply_review(_preview(), rev, ["rick-review-s1-portrait.mp4", "old.mp4"])
    assert any(x["code"] == "invalid_source_url" for x in out["blockers"])


def test_review_html_escapes_narration_and_provenance():
    preview = _preview()
    preview["scenes"][0]["text"] = '<img src=x onerror="alert(1)">'
    review = make_review(preview)
    review["scenes"][0]["credit"] = '<script>alert("bad")</script>'
    result = render_review_html(preview, review)
    assert "&lt;img" in result
    assert "<script>" not in result
    assert "&lt;script&gt;" in result
    assert "Rick — Revisão editorial" in result
    assert "<!doctype html>" in result


def test_rejects_stale_or_incomplete_review():
    rev = make_review(_preview())
    rev["scenes"].pop()
    with pytest.raises(ValueError, match="exatamente uma"):
        apply_review(_preview(), rev, ["old.mp4"])


def test_optional_thumbnails_use_only_generated_relative_path():
    rev = make_review(_preview())
    name = "old.mp4"
    good = render_review_html(_preview(), rev, {name: "thumbs/" + "a" * 24 + ".jpg"})
    assert "<img alt=" in good
    malicious = render_review_html(_preview(), rev, {name: "https://tracker.invalid/abc"})
    assert "<img alt=" not in malicious
