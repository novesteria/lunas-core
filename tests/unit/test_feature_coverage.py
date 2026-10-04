"""Unit tests for ``lunas.checks.feature_coverage``."""

from __future__ import annotations

import asyncio
import json

from lunas.checks.base import ValidationContext
from lunas.checks.feature_coverage import (
    FeatureCoverageCheck,
    cross_validate,
    deterministic_missing_features,
    evidence_visible_in_code,
    extract_brief_features,
    feature_keyword_markers,
)
from lunas.design_dna import Brand, DesignDNA, Fonts, Palette, Philosophy
from lunas.result import LayerKind, Verdict


def _dna(features=None, notes="", intent=""):
    pal = Palette(primary="", secondary="", accent="", bg="", fg="")
    fnt = Fonts(heading="", body="")
    return DesignDNA(
        version=1, archetype="", brand=Brand(False, pal, fnt, []),
        philosophy=Philosophy("", "", {}), density="", motion="",
        features=features or [], notes=notes, intent=intent,
    )


class _FakeLLM:
    def __init__(self, text: str, *, raises: Exception | None = None):
        self._text = text
        self._raises = raises

    async def judge(self, prompt: str, *, max_tokens: int = 2048, temperature: float = 0.0) -> str:
        if self._raises is not None:
            raise self._raises
        return self._text


# ----- pure helpers -------------------------------------------------------


def test_feature_keyword_markers_strips_stopwords():
    markers = feature_keyword_markers("Dark mode toggle for the user")
    # 'mode' is not in stopwords, neither is 'toggle' or 'dark'
    assert "toggle" in markers or "dark" in markers


def test_feature_keyword_markers_strips_turkish_suffix():
    markers = feature_keyword_markers("localStorage'a kaydet")
    assert "localstorage" in markers


def test_extract_brief_features_bullet_list():
    description = (
        "App should have:\n"
        "- Dark mode toggle\n"
        "- LocalStorage persistence\n"
        "- Reading time estimate\n"
    )
    out = extract_brief_features(description)
    assert any("dark mode toggle" in f.lower() for f in out)
    assert any("localstorage persistence" in f.lower() for f in out)


def test_evidence_visible_in_code():
    assert evidence_visible_in_code("#theme-toggle in app.js", "document.getelementbyid('#theme-toggle')")
    # Evidence names "stopwatch" but code only has "timer" — not visible.
    assert not evidence_visible_in_code("the stopwatch works", "function timer() {}")


def test_evidence_pure_prose_rejected():
    """Generic prose like 'the feature works' should NOT redeem."""
    assert not evidence_visible_in_code(
        "The feature works correctly",
        "function calculatetip() { return 0; }",
    )


def test_deterministic_missing_scans_lowercased():
    features = ["Dark mode toggle", "Calculate tip"]
    code = "function calculate() { return 0; }"  # has 'calculate', missing 'dark/toggle'
    missing = deterministic_missing_features(features, code.lower())
    assert "Dark mode toggle" in missing
    assert "Calculate tip" not in missing


def test_deterministic_finds_no_misses_when_all_match():
    features = ["Calculate tip", "Save to localStorage"]
    code = "function calculate() { localStorage.setItem(...); }"
    missing = deterministic_missing_features(features, code.lower())
    assert missing == {}


# ----- cross_validate -----------------------------------------------------


def test_cross_validate_demotes_unbacked_present():
    """LLM says 'present' but Stage 1 found nothing and evidence is prose → demote."""
    features = ["Dark mode toggle"]
    det_missing = {"Dark mode toggle": ["toggle", "dark"]}
    llm = [{
        "feature": "Dark mode toggle",
        "status": "present",
        "evidence": "the page has it",
    }]
    code_lower = "function f() {}"
    present, missing, overrides = cross_validate(features, det_missing, llm, code_lower)
    assert present == []
    assert overrides == 1
    assert missing[0]["feature"] == "Dark mode toggle"


def test_cross_validate_rescue_path():
    """LLM points at a concrete identifier — keyword scan rescued."""
    features = ["Statistics Display Panel"]
    det_missing = {"Statistics Display Panel": ["statistics"]}
    llm = [{
        "feature": "Statistics Display Panel",
        "status": "present",
        "evidence": "metrics-grid in dashboard.tsx",
    }]
    code_lower = "<div id='metrics-grid'></div>"
    present, missing, overrides = cross_validate(features, det_missing, llm, code_lower)
    assert "Statistics Display Panel" in present
    assert overrides == 0


def test_cross_validate_passes_when_markers_and_llm_agree():
    features = ["Calculate tip amount"]
    det_missing = {}  # markers found
    llm = [{"feature": "Calculate tip amount", "status": "present", "evidence": "calc.js"}]
    present, missing, _ = cross_validate(features, det_missing, llm, "function calculate() {}")
    assert present == ["Calculate tip amount"]
    assert missing == []


# ----- Full layer ---------------------------------------------------------


def test_layer_metadata():
    layer = FeatureCoverageCheck()
    assert layer.NAME == "feature_coverage"
    assert LayerKind.hybrid == layer.KIND


def test_layer_skipped_no_brief(tmp_path):
    layer = FeatureCoverageCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"], brief=None,
                            llm_client=_FakeLLM(""))
    assert asyncio.run(layer.run_async(ctx)).verdict == Verdict.skipped


def test_layer_skipped_no_features(tmp_path):
    (tmp_path / "p.html").write_text("<div></div>")
    layer = FeatureCoverageCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"],
                            brief=_dna(features=[], notes=""), llm_client=_FakeLLM(""))
    assert asyncio.run(layer.run_async(ctx)).verdict == Verdict.skipped


def test_layer_skipped_no_llm(tmp_path):
    (tmp_path / "p.html").write_text("<div></div>")
    layer = FeatureCoverageCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"],
                            brief=_dna(features=["Dark mode"]), llm_client=None)
    assert asyncio.run(layer.run_async(ctx)).verdict == Verdict.skipped


def test_layer_passes_when_all_features_present(tmp_path):
    (tmp_path / "app.js").write_text(
        "function calculate() { localStorage.setItem('x', 1); }"
    )
    fake = _FakeLLM(json.dumps({
        "results": [
            {"feature": "Calculate tip", "status": "present", "evidence": "calculate() in app.js"},
            {"feature": "Save to localStorage", "status": "present", "evidence": "localStorage.setItem"},
        ],
    }))
    layer = FeatureCoverageCheck()
    ctx = ValidationContext(
        code_path=tmp_path, stacks=["static_html"],
        brief=_dna(features=["Calculate tip", "Save to localStorage"]),
        llm_client=fake,
    )
    result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.passed
    assert result.details["total"] == 2


def test_layer_fails_when_llm_hallucinates(tmp_path):
    """LLM says 'present' for a feature with no markers and no concrete evidence."""
    (tmp_path / "app.js").write_text("function basic() { return 1; }")
    fake = _FakeLLM(json.dumps({
        "results": [
            {"feature": "Dark mode toggle", "status": "present", "evidence": "it's there"},
        ],
    }))
    layer = FeatureCoverageCheck()
    ctx = ValidationContext(
        code_path=tmp_path, stacks=["static_html"],
        brief=_dna(features=["Dark mode toggle"]),
        llm_client=fake,
    )
    result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.failed
    assert result.override_fired is True
    assert result.details["llm_overrides"] == 1


def test_layer_falls_back_when_llm_unparseable(tmp_path):
    (tmp_path / "app.js").write_text("function calculate() {}")
    fake = _FakeLLM("not valid json")
    layer = FeatureCoverageCheck()
    ctx = ValidationContext(
        code_path=tmp_path, stacks=["static_html"],
        brief=_dna(features=["Calculate tip"]),
        llm_client=fake,
    )
    result = asyncio.run(layer.run_async(ctx))
    # Keyword scan finds 'calculate' → fallback passes
    assert result.verdict == Verdict.passed
    assert result.details["fallback"] is True


def test_layer_fallback_fails_when_markers_missing(tmp_path):
    (tmp_path / "app.js").write_text("function basic() {}")
    fake = _FakeLLM("garbage response")
    layer = FeatureCoverageCheck()
    ctx = ValidationContext(
        code_path=tmp_path, stacks=["static_html"],
        brief=_dna(features=["Dark mode toggle"]),
        llm_client=fake,
    )
    result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.failed
    assert result.details["fallback"] is True


def test_layer_falls_back_on_llm_error(tmp_path):
    (tmp_path / "app.js").write_text("function calculate() {}")
    fake = _FakeLLM("", raises=RuntimeError("api down"))
    layer = FeatureCoverageCheck()
    ctx = ValidationContext(
        code_path=tmp_path, stacks=["static_html"],
        brief=_dna(features=["Calculate tip"]),
        llm_client=fake,
    )
    result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.passed
    assert result.details["fallback"] is True
    assert "api down" in result.details["error"]


# ---- Semantic-evidence rescue (false-negative escape hatch) ---------------


def test_semantic_evidence_matches_named_mechanism():
    from lunas.checks.feature_coverage import search_semantic_evidence

    hit = search_semantic_evidence(
        "Beep sound on finish",
        "const ctx = new AudioContext(); ctx.createOscillator();",
    )
    assert hit is not None and "AudioContext" in hit


def test_semantic_evidence_ignores_stub_html_id():
    # Only the HTML id is present, no textContent flip — must NOT rescue.
    from lunas.checks.feature_coverage import search_semantic_evidence

    assert search_semantic_evidence("Mode label", "<div id='mode-label'></div>") is None


def test_semantic_evidence_no_class_returns_none():
    from lunas.checks.feature_coverage import search_semantic_evidence

    assert search_semantic_evidence("Some unrelated feature", "const x = 1;") is None


def test_cross_validate_rescues_false_negative():
    # Stage 1 found the marker (feature not in deterministic_missing); the judge
    # said "missing"; the code has the textContent flip → rescued to present.
    code = "el.textContent = isWork ? 'WORK' : 'BREAK';".lower()
    present, missing, _ = cross_validate(
        features=["Mode label"],
        deterministic_missing={},
        llm_results=[{"feature": "Mode label", "status": "missing", "evidence": ""}],
        code_lower=code,
    )
    assert "Mode label" in present
    assert missing == []


def test_cross_validate_keeps_missing_without_mechanism():
    # Judge says missing and the code has no recognizable mechanism → stays missing.
    present, missing, _ = cross_validate(
        features=["Mode label"],
        deterministic_missing={},
        llm_results=[{"feature": "Mode label", "status": "missing", "evidence": ""}],
        code_lower="const x = 1;",
    )
    assert present == []
    assert [m["feature"] for m in missing] == ["Mode label"]
