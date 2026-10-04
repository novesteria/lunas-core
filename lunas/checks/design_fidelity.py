"""Layer #20 — LLM-as-judge for design-brief fidelity, with a
deterministic evidence override.

Hybrid layer: the LLM scores four dimensions (palette, philosophy
fidelity, density+motion, tone microcopy) and a deterministic
literal-string scan can CAP the LLM's scores when evidence is missing.
The deterministic floor is the difference between "Lunas judges" and
"Lunas rubber-stamps".

Skip-clean when:

- ``brief`` is None or empty (quick-mode user — no API cost).
- ``llm_client`` is None (caller passed ``no_llm=True``).
- Code blob is empty (nothing to judge).
- LLM call fails (return error verdict — never silently green-light).

Pass threshold:

- ``overall_score >= 6`` (out of 10).
- No individual dimension below 3.

The thresholds are intentionally conservative. We only fail builds
that REALLY ignored the brief, not ones that interpreted it loosely.
"""

from __future__ import annotations

import contextlib
import re
import time
from typing import Any

from lunas.checks._llm_helpers import (
    collect_code_blob,
    design_dna_is_empty,
    parse_json_verdict,
)
from lunas.checks.base import CheckLayer, ValidationContext
from lunas.design_dna import DesignDNA
from lunas.result import LayerKind, LayerResult, Verdict

_MIN_OVERALL_SCORE = 6
_MIN_DIMENSION_SCORE = 3
_MAX_TOKENS = 1500


# Philosophies whose contracts ban specific CSS patterns. Extend as
# new philosophy presets are added; the deterministic check only fires
# on philosophies registered here.
_PHILOSOPHY_FORBIDDEN_PATTERNS: dict[str, list[str]] = {
    "apple-flat":            [r"linear-gradient", r"box-shadow:\s*0\s+0", r"backdrop-filter", r"text-shadow"],
    "kenya-hara-minimalism": [r"linear-gradient", r"box-shadow", r"text-shadow", r"backdrop-filter"],
    "swiss-international":   [r"linear-gradient", r"text-shadow"],
    "brutalist":             [r"border-radius:\s*[1-9]\d*px"],
    "memphis-80s":           [],
}


def _font_present(font: str, code_lower: str) -> bool:
    """True if ``font`` appears as a whole word or phrase in the code blob.

    Matches ``font-family: 'Lora'`` and Google Fonts URLs such as
    ``family=Source+Sans``; does not match substrings inside other words
    (``inter`` inside ``internal``). ``code_lower`` must already be
    lower-cased.
    """
    name = font.strip().lower()
    if not name:
        return True
    body = r"[\s+]+".join(re.escape(part) for part in name.split())
    pattern = r"(?<![a-z0-9])" + body + r"(?![a-z0-9])"
    return re.search(pattern, code_lower) is not None


def _hex_search_variants(hex_value: str) -> list[str]:
    """Case-and-format variants of a hex color for literal grep.

    Covers: with/without leading ``#``, upper/lower case, and
    ``rgb()`` / ``rgba()`` equivalents. Misses HSL — acceptable in
    v1 since CSS rarely uses HSL when the brief specifies hex.
    """
    h = (hex_value or "").lstrip("#").strip().lower()
    if len(h) not in (3, 6) or not all(c in "0123456789abcdef" for c in h):
        return []
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    variants = [f"#{h}", f"#{h.upper()}", h, h.upper()]
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        variants.extend([
            f"rgb({r}, {g}, {b})",
            f"rgb({r},{g},{b})",
            f"rgba({r}, {g}, {b}",
            f"rgba({r},{g},{b}",
        ])
    except ValueError:
        pass
    return variants


def _render_brief_block(dna: DesignDNA) -> str:
    """Compact rendering of the DesignDNA for the judge prompt. Skips
    sections the user didn't fill in so the model doesn't read
    'primary: not set' lines.
    """
    parts: list[str] = []
    if dna.archetype:
        parts.append(f"Archetype: {dna.archetype}")

    pal = dna.brand.palette
    pal_lines = [
        f"  - {name}: {hex_val}"
        for name, hex_val in (
            ("primary", pal.primary),
            ("secondary", pal.secondary),
            ("accent", pal.accent),
            ("bg", pal.bg),
            ("fg", pal.fg),
        )
        if hex_val
    ]
    if pal_lines:
        parts.append("Palette:\n" + "\n".join(pal_lines))

    fonts = dna.brand.fonts
    font_lines = [
        f"  - {role}: {family}"
        for role, family in (("heading", fonts.heading), ("body", fonts.body))
        if family
    ]
    if font_lines:
        parts.append("Fonts:\n" + "\n".join(font_lines))

    if dna.brand.tone:
        parts.append(
            "Tone keywords (microcopy must feel this way): "
            + ", ".join(dna.brand.tone)
        )

    if dna.philosophy.id:
        rules = dna.philosophy.rules or {}
        rule_lines = [f"  - {k.replace('_', ' ')}: {v}" for k, v in rules.items()]
        rules_block = "\n".join(rule_lines) if rule_lines else "  (no extra rules)"
        parts.append(
            f"Philosophy: {dna.philosophy.id} ({dna.philosophy.label or 'no label'})\n"
            f"Concrete rules the philosophy enforces:\n{rules_block}"
        )

    if dna.density:
        parts.append(f"Density: {dna.density}")
    if dna.motion:
        parts.append(f"Motion: {dna.motion}")
    if dna.notes:
        parts.append(f"Notes: {dna.notes}")

    return "\n\n".join(parts) if parts else "(empty brief)"


def deterministic_evidence_override(
    dna: DesignDNA,
    code_blob: str,
    verdict: dict[str, Any],
) -> dict[str, Any]:
    """Cap LLM scores when literal evidence contradicts them.

    The deterministic layer never RAISES a passing build to failing on
    its own — it only LOWERS scores when evidence is missing. When at
    least one cap fires, ``forced_fail`` is set so ``_decide`` returns
    a failure regardless of numeric thresholds.
    """
    if not isinstance(verdict, dict):
        return verdict
    dimensions = verdict.get("dimensions") or []
    if not isinstance(dimensions, list) or not dimensions:
        return verdict
    if not code_blob:
        return verdict

    code_lower = code_blob.lower()
    overrides: list[str] = []   # DOWNWARD adjustments (missing evidence) — force a fail
    touched: list[str] = []     # every score change (up or down) — recompute overall

    def _apply(name: str, new_score: int, reason: str, *, cap_only: bool) -> None:
        for d in dimensions:
            if not isinstance(d, dict) or d.get("name") != name:
                continue
            try:
                original = int(d.get("score") or 0)
            except (TypeError, ValueError):
                original = 0
            # `_cap` only ever lowers; `_force` replaces (up or down).
            target = min(new_score, original) if cap_only else new_score
            if target == original:
                break
            d["score"] = target
            down = target < original
            verb = "capped at" if down else "raised to"
            d["comment"] = (
                f"OVERRIDE — deterministic check: {reason} "
                f"LLM score {original}/10 {verb} {target}/10. "
            ) + str(d.get("comment") or "")
            touched.append(f"{name} {original}->{target}")
            # Only a DOWNWARD move (evidence missing) fails the build. Raising a
            # too-harsh LLM score corrects the number without failing an honest build.
            if down:
                overrides.append(f"{name} {original}->{target} ({reason})")
            break

    def _cap(name: str, max_score: int, reason: str) -> None:
        _apply(name, max_score, reason, cap_only=True)

    def _force(name: str, new_score: int, reason: str) -> None:
        _apply(name, new_score, reason, cap_only=False)

    # Palette: score deterministically from how many required hex codes
    # literally appear, replacing the LLM's palette judgment entirely. Score =
    # round(found / required * 10). The same CSS always yields the same palette
    # number, so a passing build no longer flips to failing between runs on
    # inter-round LLM variance (and a too-harsh LLM palette score is corrected
    # upward without failing the build).
    pal = dna.brand.palette
    required_hex = [h for h in (pal.primary, pal.secondary, pal.accent, pal.bg, pal.fg) if h]
    if required_hex:
        missing = []
        for hex_val in required_hex:
            variants = _hex_search_variants(hex_val)
            if not variants:
                continue
            if not any(v.lower() in code_lower for v in variants):
                missing.append(hex_val)
        found = len(required_hex) - len(missing)
        palette_score = round((found / len(required_hex)) * 10)
        reason = (
            f"{found}/{len(required_hex)} required hex codes present in code"
            + (f"; missing: {', '.join(missing)}" if missing else "")
            + "."
        )
        _force("palette", palette_score, reason)

    # Fonts: required font families must appear as whole words (a
    # font-family declaration or a Google Fonts URL). Substrings inside
    # other words ("inter" in "internal") do not count. If NONE of the
    # required fonts is present the brief's typography was ignored, and
    # that is hard evidence: the philosophy score is capped below the
    # per-dimension floor so the layer fails deterministically. If only
    # some are missing the score is capped at 4 (soft evidence).
    fonts = dna.brand.fonts
    required_fonts = [f for f in (fonts.heading, fonts.body) if f]
    if required_fonts:
        missing_fonts = [f for f in required_fonts if not _font_present(f, code_lower)]
        if missing_fonts and len(missing_fonts) == len(required_fonts):
            _cap(
                "philosophy", 2,
                f"none of the required font(s) {', '.join(missing_fonts)} found in code.",
            )
        elif missing_fonts:
            _cap(
                "philosophy", 4,
                f"required font(s) {', '.join(missing_fonts)} NOT FOUND in code.",
            )

    # Philosophy: forbidden patterns must NOT appear.
    if dna.philosophy.id and dna.philosophy.id in _PHILOSOPHY_FORBIDDEN_PATTERNS:
        forbidden = _PHILOSOPHY_FORBIDDEN_PATTERNS[dna.philosophy.id]
        violations = [p for p in forbidden if re.search(p, code_blob, flags=re.IGNORECASE)]
        if violations:
            _cap(
                "philosophy", 4,
                f"philosophy '{dna.philosophy.id}' forbids these patterns "
                f"but code contains: {', '.join(violations)}.",
            )

    # Any score change (up or down) means the overall must be recomputed.
    if touched:
        scores: list[int] = []
        for d in dimensions:
            if isinstance(d, dict):
                with contextlib.suppress(TypeError, ValueError):
                    scores.append(int(d.get("score") or 0))
        if scores:
            verdict["overall_score"] = round(sum(scores) / len(scores))

    # Only downward overrides (missing evidence) force the build to fail.
    if overrides:
        existing_raw = verdict.get("missing")
        existing: list[Any] = list(existing_raw) if isinstance(existing_raw, list) else []
        verdict["missing"] = [f"DETERMINISTIC OVERRIDE: {'; '.join(overrides)}"] + existing
        verdict["forced_fail"] = True

    return verdict


def _build_judge_prompt(brief: str, code_blob: str) -> str:
    """Compose the user prompt for the judge model.

    The prompt's specificity (forbid-list, evidence requirement,
    override warning) is load-bearing — keep it verbatim.
    """
    return f"""You are auditing whether a generated codebase honors the
design brief the user gave us. Read the brief and the code, then
score each dimension 0-10. Be specific — point to file/selector
evidence in your comments.

YOU ARE NOT A CHEERLEADER. Score honestly, with downward bias when
the brief is clearly violated.

DESIGN BRIEF (what the user asked for):
{brief}

CODE THAT WAS GENERATED:
{code_blob}

Score these four dimensions independently:

1. palette          — does CSS use the requested colors? Hex values close
                      to what was asked is fine (within ~10% RGB distance).
                      If the brief specifies a LIGHT palette but the code
                      defaults to dark mode, cap at 3.
                      If the brief specified no palette, score 8 by default.

2. philosophy       — does the code embody the philosophy's concrete rules?
                      Cap at 4 if the philosophy explicitly forbids gradients/
                      glows/shadows and the code uses `linear-gradient`,
                      `box-shadow: 0 0 *`, `backdrop-filter`, `text-shadow`.
                      If no philosophy was selected, score 8.

3. density_motion   — does the spacing rhythm match? Do CSS transitions match
                      the requested motion style? Cap at 4 if the brief says
                      "abrupt" but the code adds transitions everywhere, or
                      vice-versa. If unset, score 8.

4. tone_microcopy   — does the user-facing copy feel like the requested tone
                      keywords? Cap at 5 if all UI strings are generic defaults
                      regardless of requested tone. If unset, score 8.

DETERMINISTIC GATEKEEPER (runs after your verdict): a literal-string
scan checks (a) every required palette hex appears somewhere in the
code, (b) every required font family appears, (c) the philosophy's
forbidden patterns DO NOT appear. If you scored palette > 4 but the
hexes aren't in the code, your palette score is overridden to 4.
Score honestly — the override only fires when you lied. Your evidence
comments must cite literal code (selector, line, value) so the
override can be reconciled if it disagrees.

Respond with JSON ONLY in this exact shape (no prose):
{{
  "overall_score": <int 0-10, the rounded mean of the four dimensions>,
  "dimensions": [
    {{ "name": "palette",        "score": <0-10>, "comment": "<short evidence>" }},
    {{ "name": "philosophy",     "score": <0-10>, "comment": "<short evidence>" }},
    {{ "name": "density_motion", "score": <0-10>, "comment": "<short evidence>" }},
    {{ "name": "tone_microcopy", "score": <0-10>, "comment": "<short evidence>" }}
  ],
  "missing": [ "<bullet 1>", "<bullet 2>" ]
}}
"""


def decide_verdict(verdict: dict[str, Any]) -> tuple[Verdict, str, dict[str, Any]]:
    """Reduce the LLM verdict into (verdict, summary, details).

    Pure function — easy to unit-test without an LLM call.
    """
    overall = int(verdict.get("overall_score", 0) or 0)
    dimensions = verdict.get("dimensions") or []
    missing = verdict.get("missing") or []
    forced_fail = bool(verdict.get("forced_fail", False))

    if not isinstance(dimensions, list):
        dimensions = []
    if not isinstance(missing, list):
        missing = []

    weak_dims: list[str] = []
    dim_summary: list[dict[str, Any]] = []
    for d in dimensions:
        if not isinstance(d, dict):
            continue
        name = str(d.get("name") or "?")
        try:
            score = int(d.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        comment = str(d.get("comment") or "")
        dim_summary.append({"name": name, "score": score, "comment": comment})
        if score < _MIN_DIMENSION_SCORE:
            weak_dims.append(f"{name} ({score}/10)")

    passed = (not forced_fail) and overall >= _MIN_OVERALL_SCORE and not weak_dims

    details: dict[str, Any] = {
        "overall_score": overall,
        "dimensions": dim_summary,
        "missing": missing,
        "forced_fail": forced_fail,
    }

    if passed:
        return (
            Verdict.passed,
            f"Design fidelity met threshold (overall {overall}/10)",
            details,
        )

    if forced_fail:
        summary = "Design fidelity forced-failed by deterministic evidence override"
    elif weak_dims:
        summary = (
            f"Design fidelity failed (overall {overall}/10) — "
            f"weak dimensions: {', '.join(weak_dims)}"
        )
    else:
        summary = f"Design fidelity below threshold (overall {overall}/10)"
    return Verdict.failed, summary, details


class DesignFidelityCheck(CheckLayer):
    """Layer #20 — LLM-as-judge for design-brief fidelity with deterministic override."""

    NAME = "design_fidelity"
    KIND = LayerKind.hybrid
    APPLIES_TO = ("static_html", "node", "python")
    DESCRIPTION = (
        "LLM judges whether the generated code honors the design brief "
        "(palette, philosophy, density+motion, tone). A deterministic "
        "evidence override caps the LLM's scores when required hex codes / "
        "fonts / forbidden patterns disagree with the verdict."
    )

    async def run_async(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        root = ctx.code_path
        if not root.is_dir():
            return self._skip("code_path is not a directory")

        dna = ctx.brief
        if dna is None or design_dna_is_empty(dna):
            return self._skip("No design brief (or empty brief) — nothing to judge")

        if ctx.llm_client is None:
            return self._skip("No LLM client configured (use --no-llm to silence)")

        code_blob = collect_code_blob(root)
        if not code_blob.strip():
            return self._skip("No readable code under code_path")

        brief = _render_brief_block(dna)
        prompt = _build_judge_prompt(brief, code_blob)

        try:
            raw = await ctx.llm_client.judge(prompt, max_tokens=_MAX_TOKENS)
        except Exception as exc:
            return self._result(
                Verdict.failed,
                summary=f"design fidelity LLM call failed: {type(exc).__name__}",
                start_time=start,
                details={"error": repr(exc)},
            )

        verdict = parse_json_verdict(raw or "")
        if not verdict:
            return self._result(
                Verdict.failed,
                summary="design fidelity LLM returned unparseable JSON",
                start_time=start,
                details={"raw_tail": (raw or "")[-500:]},
            )

        verdict = deterministic_evidence_override(dna, code_blob, verdict)
        outcome, summary, details = decide_verdict(verdict)
        override_fired = bool(verdict.get("forced_fail", False))
        return self._result(
            outcome,
            summary=summary,
            start_time=start,
            details=details,
            override_fired=override_fired,
        )

    def run(self, ctx: ValidationContext) -> LayerResult:  # pragma: no cover
        import asyncio
        return asyncio.run(self.run_async(ctx))


__all__ = [
    "DesignFidelityCheck",
    "deterministic_evidence_override",
    "decide_verdict",
]
