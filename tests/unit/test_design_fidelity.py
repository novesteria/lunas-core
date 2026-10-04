"""Unit tests for ``lunas.checks.design_fidelity``."""

from __future__ import annotations

import asyncio
import json

from lunas.checks._llm_helpers import design_dna_is_empty
from lunas.checks.base import ValidationContext
from lunas.checks.design_fidelity import (
    DesignFidelityCheck,
    decide_verdict,
    deterministic_evidence_override,
)
from lunas.design_dna import Brand, DesignDNA, Fonts, Palette, Philosophy
from lunas.result import LayerKind, Verdict

# ----- helpers -------------------------------------------------------------


def _dna(*, palette=None, fonts=None, philosophy_id="", forbidden_rules=None):
    pal = palette or Palette(primary="#1a3d2e", secondary="", accent="", bg="", fg="")
    fnt = fonts or Fonts(heading="", body="")
    return DesignDNA(
        version=1,
        archetype="modern-saas",
        brand=Brand(has_logo=False, palette=pal, fonts=fnt, tone=[]),
        philosophy=Philosophy(
            id=philosophy_id,
            label=philosophy_id or "",
            rules=forbidden_rules or {},
        ),
        density="moderate",
        motion="subtle",
    )


class _FakeLLM:
    """Stub LLM client returning a fixed string."""

    def __init__(self, text: str, *, raises: Exception | None = None):
        self._text = text
        self._raises = raises
        self.calls: list[str] = []

    async def judge(self, prompt: str, *, max_tokens: int = 1500, temperature: float = 0.0) -> str:
        self.calls.append(prompt)
        if self._raises is not None:
            raise self._raises
        return self._text


# ----- design_dna_is_empty -------------------------------------------------


def test_empty_dna_recognised():
    pal = Palette(primary="", secondary="", accent="", bg="", fg="")
    fnt = Fonts(heading="", body="")
    dna = DesignDNA(
        version=1, archetype="", brand=Brand(False, pal, fnt, []),
        philosophy=Philosophy("", "", {}), density="", motion="",
    )
    assert design_dna_is_empty(dna) is True
    assert design_dna_is_empty(None) is True


def test_nonempty_dna_recognised():
    dna = _dna()
    assert design_dna_is_empty(dna) is False


# ----- deterministic_evidence_override -------------------------------------


def test_palette_forced_to_zero_when_hex_absent():
    # Palette is scored deterministically = round(found/required * 10). With the
    # single required hex absent, found=0 → 0, and a downward move forces a fail.
    dna = _dna(palette=Palette(primary="#1a3d2e", secondary="", accent="", bg="", fg=""))
    verdict = {
        "overall_score": 8,
        "dimensions": [
            {"name": "palette", "score": 9, "comment": "looks great"},
            {"name": "philosophy", "score": 7, "comment": ""},
        ],
    }
    code = "body { color: #ffffff; }"  # No #1a3d2e
    out = deterministic_evidence_override(dna, code, verdict)
    pal_dim = next(d for d in out["dimensions"] if d["name"] == "palette")
    assert pal_dim["score"] == 0
    assert out["forced_fail"] is True
    assert "OVERRIDE" in pal_dim["comment"]


def test_palette_forced_up_when_all_present():
    # All required hexes present → round(1/1 * 10) = 10. An UPWARD correction of
    # a too-harsh LLM score must NOT force a fail.
    dna = _dna(palette=Palette(primary="#1a3d2e", secondary="", accent="", bg="", fg=""))
    verdict = {
        "overall_score": 8,
        "dimensions": [{"name": "palette", "score": 9, "comment": ""}],
    }
    code = ".btn { background: #1a3d2e; }"
    out = deterministic_evidence_override(dna, code, verdict)
    assert out["dimensions"][0]["score"] == 10
    assert "forced_fail" not in out


def test_rgb_form_counts_as_present():
    dna = _dna(palette=Palette(primary="#1a3d2e", secondary="", accent="", bg="", fg=""))
    verdict = {
        "overall_score": 8,
        "dimensions": [{"name": "palette", "score": 9, "comment": ""}],
    }
    # 1a3d2e = rgb(26, 61, 46) — counts as present, so palette forces to 10.
    code = ".btn { background: rgb(26, 61, 46); }"
    out = deterministic_evidence_override(dna, code, verdict)
    assert out["dimensions"][0]["score"] == 10
    assert "forced_fail" not in out


def test_philosophy_cap_on_forbidden_pattern():
    dna = _dna(philosophy_id="apple-flat")
    verdict = {
        "overall_score": 8,
        "dimensions": [{"name": "philosophy", "score": 9, "comment": ""}],
    }
    code = ".card { background: linear-gradient(45deg, red, blue); }"
    out = deterministic_evidence_override(dna, code, verdict)
    assert out["dimensions"][0]["score"] == 4
    assert out["forced_fail"] is True


# ----- decide_verdict ------------------------------------------------------


def test_decide_passes_above_threshold():
    verdict = {
        "overall_score": 7,
        "dimensions": [
            {"name": "palette", "score": 8, "comment": ""},
            {"name": "philosophy", "score": 7, "comment": ""},
        ],
    }
    outcome, summary, _ = decide_verdict(verdict)
    assert outcome == Verdict.passed


def test_decide_fails_on_low_overall():
    verdict = {"overall_score": 4, "dimensions": []}
    outcome, _, _ = decide_verdict(verdict)
    assert outcome == Verdict.failed


def test_decide_fails_on_weak_dimension():
    verdict = {
        "overall_score": 7,
        "dimensions": [
            {"name": "palette", "score": 8, "comment": ""},
            {"name": "philosophy", "score": 2, "comment": ""},
        ],
    }
    outcome, _, _ = decide_verdict(verdict)
    assert outcome == Verdict.failed


def test_decide_forced_fail_trumps_score():
    verdict = {
        "overall_score": 9,
        "dimensions": [{"name": "palette", "score": 9, "comment": ""}],
        "forced_fail": True,
    }
    outcome, summary, _ = decide_verdict(verdict)
    assert outcome == Verdict.failed
    assert "forced-failed" in summary.lower()


# ----- Full layer ----------------------------------------------------------


def test_layer_metadata():
    layer = DesignFidelityCheck()
    assert layer.NAME == "design_fidelity"
    assert LayerKind.hybrid == layer.KIND


def test_layer_skipped_no_brief(tmp_path):
    (tmp_path / "p.html").write_text("<div>x</div>")
    layer = DesignFidelityCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"], brief=None,
                            llm_client=_FakeLLM("{}"))
    result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.skipped


def test_layer_skipped_no_llm(tmp_path):
    (tmp_path / "p.html").write_text("<div>x</div>")
    layer = DesignFidelityCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"],
                            brief=_dna(), llm_client=None)
    result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.skipped


def test_layer_skipped_no_code(tmp_path):
    layer = DesignFidelityCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"],
                            brief=_dna(), llm_client=_FakeLLM("{}"))
    result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.skipped


def test_layer_passes_with_good_llm_verdict(tmp_path):
    (tmp_path / "style.css").write_text(".btn { background: #1a3d2e; }")
    fake = _FakeLLM(json.dumps({
        "overall_score": 8,
        "dimensions": [
            {"name": "palette", "score": 9, "comment": "uses #1a3d2e in style.css"},
            {"name": "philosophy", "score": 7, "comment": ""},
            {"name": "density_motion", "score": 8, "comment": ""},
            {"name": "tone_microcopy", "score": 8, "comment": ""},
        ],
        "missing": [],
    }))
    layer = DesignFidelityCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"],
                            brief=_dna(), llm_client=fake)
    result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.passed


def test_layer_fails_when_llm_rubberstamps_missing_hex(tmp_path):
    """LLM scores palette 9 but the hex #1a3d2e is not in the code → cap to 4 → fail."""
    (tmp_path / "style.css").write_text(".btn { background: #000000; }")
    fake = _FakeLLM(json.dumps({
        "overall_score": 8,
        "dimensions": [
            {"name": "palette", "score": 9, "comment": "looks good"},
            {"name": "philosophy", "score": 7, "comment": ""},
            {"name": "density_motion", "score": 8, "comment": ""},
            {"name": "tone_microcopy", "score": 8, "comment": ""},
        ],
        "missing": [],
    }))
    layer = DesignFidelityCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"],
                            brief=_dna(), llm_client=fake)
    result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.failed
    assert result.override_fired is True


def test_layer_fails_on_llm_error(tmp_path):
    (tmp_path / "p.html").write_text("<div>x</div>")
    fake = _FakeLLM("", raises=RuntimeError("network down"))
    layer = DesignFidelityCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"],
                            brief=_dna(), llm_client=fake)
    result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.failed
    assert "network down" in str(result.details["error"])


def test_layer_fails_on_unparseable_llm(tmp_path):
    (tmp_path / "p.html").write_text("<div>x</div>")
    fake = _FakeLLM("not json at all, just prose")
    layer = DesignFidelityCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"],
                            brief=_dna(), llm_client=fake)
    result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.failed
    assert "unparseable" in result.summary.lower()
