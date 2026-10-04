"""Layer #21 — hybrid feature-coverage check (keyword scan + LLM judge).

The strongest "did the agent actually deliver what was asked?" signal
in the validator. Two-stage verdict:

**Stage 1 (deterministic keyword scan):** for each requested feature,
derive 1-3 keyword markers from the label (after stopword strip). If
NONE of the markers appear anywhere in the code blob, the feature is
*definitively missing* — no LLM second-guess can rescue it.

**Stage 2 (LLM-as-judge):** hand the LLM the full feature list + code
and ask present/missing/partial per feature. Then CROSS-VALIDATE: if
the LLM says "present" but Stage 1 found no markers, the LLM verdict
is **overridden to missing** — unless the LLM's evidence string itself
points at a concrete code symbol the scanner can locate (rescue path
for legitimate hits the keyword scanner missed).

Skip-clean when:

- ``brief`` is None or carries no features.
- ``llm_client`` is None.
- Code blob is empty.

Failure mode is **blocking**, not optional. When the check cannot run
(LLM call fails, parse fails, code unreadable), the result is a FAIL.
"Couldn't verify" must not become "PASSED".
"""

from __future__ import annotations

import re
import time
from typing import Any

from lunas.checks._llm_helpers import (
    collect_code_blob,
    parse_json_verdict,
)
from lunas.checks.base import CheckLayer, ValidationContext
from lunas.design_dna import DesignDNA
from lunas.result import LayerKind, LayerResult, Verdict

_MAX_TOKENS = 2048

# Feature coverage judges the frontend only — no `.py`. An empty result means
# a non-frontend stack, which the layer skips rather than false-fails.
_FRONTEND_EXTS: tuple[str, ...] = (
    ".html", ".htm", ".js", ".mjs", ".cjs", ".jsx", ".tsx", ".ts", ".css",
)


# Stopwords for feature-label keyword extraction (EN + TR).
_STOPWORDS: frozenset[str] = frozenset([
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for",
    "with", "by", "at", "as", "is", "are", "be", "this", "that",
    "real", "time", "real-time", "realtime", "user", "feature",
    "button", "panel", "area", "display", "show", "shows", "showing",
    "all", "each", "every", "one", "two", "three", "page", "app",
    "ve", "ile", "için", "bir", "bu", "şu", "olan", "gibi", "her",
    "tüm", "sayfa", "uygulama", "kullanıcı", "göster", "gösterir",
])


_PROSE_FILLER: frozenset[str] = frozenset([
    "the", "and", "has", "with", "from", "into", "this", "that",
    "works", "present", "exists", "feature", "button", "panel",
    "input", "page", "code",
])


# Verbs that, in raw brief text, mark a sentence as "describes a feature".
# EN + TR. Used by extract_brief_features.
_FEATURE_VERBS = (
    r"toggle|save|persist|store|display|show|track|count|"
    r"calculate|estimate|filter|sort|search|remove|add|delete|"
    r"theme|dark mode|light mode|localStorage|"
    r"kaydet|göster|hesapla|tema|filtreleyip|sırala"
)


def feature_keyword_markers(label: str) -> list[str]:
    """Derive 1-3 lowercase keyword markers from a feature label.

    Strips common stopwords (EN + TR), trims Turkish suffixes attached
    after an apostrophe (``localStorage'a`` → ``localstorage``), and
    returns the longest remaining tokens.
    """
    if not label:
        return []
    tokens = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]+(?:[A-Za-z0-9']*)", label)
    cleaned: list[str] = []
    for t in tokens:
        base = t.split("'", 1)[0].lower()
        if len(base) >= 3 and base not in _STOPWORDS:
            cleaned.append(base)
    cleaned.sort(key=len, reverse=True)
    return cleaned[:3]


def extract_brief_features(description: str) -> list[str]:
    """Mine the raw brief notes/intent for feature sentences.

    Pulls bullet/numbered list lines and sentences that contain
    action verbs we recognise as feature-bearing. Returns short labels
    (≤120 chars), deduped case-insensitively.
    """
    if not description:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def _add(s: str) -> None:
        s = re.sub(r"\s+", " ", s).strip(" .,;:-*")
        if not s or len(s) < 4 or len(s) > 120:
            return
        key = s.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(s)

    for line in description.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        m = re.match(r"^(?:[-*+•]|\d+[.)])\s+(.+)", stripped)
        if m:
            _add(m.group(1))

    sentence_pat = re.compile(
        r"([^.!?\n]*\b(?:" + _FEATURE_VERBS + r")\b[^.!?\n]*)",
        re.IGNORECASE,
    )
    for m in sentence_pat.finditer(description):
        _add(m.group(1))

    return out


def evidence_visible_in_code(evidence: str, code_lower: str) -> bool:
    """Does the LLM's evidence string point at something in the code?

    Pulls identifier-shaped tokens (CSS selectors, ids, function names,
    file paths) out of the evidence string and confirms at least one
    appears in the lowercased code blob. Pure prose evidence
    ("the timer works") yields no tokens and does NOT rescue the
    feature — the LLM has to point at something concrete.
    """
    if not evidence:
        return False
    ev_lower = evidence.lower()
    candidates = re.findall(
        r"[#.]?[a-zA-Z_][a-zA-Z0-9_\-]{2,}(?:\.[a-zA-Z0-9_\-]+)*",
        ev_lower,
    )
    meaningful = [
        c.lstrip("#.") for c in candidates
        if len(c.lstrip("#.")) > 4 and c.lstrip("#.") not in _PROSE_FILLER
    ]
    return any(tok in code_lower for tok in meaningful)


def deterministic_missing_features(
    features: list[str], code_lower: str,
) -> dict[str, list[str]]:
    """Stage 1: for each feature, find features whose markers are
    completely absent from the code.

    Returns ``{feature_label: markers_we_looked_for}``.
    """
    out: dict[str, list[str]] = {}
    for label in features:
        markers = feature_keyword_markers(label)
        if not markers:
            continue
        if not any(m in code_lower for m in markers):
            out[label] = markers
    return out


def _build_judge_prompt(features: list[str], code_blob: str) -> str:
    listing = "\n".join(f"  {i + 1}. {f}" for i, f in enumerate(features))
    return f"""You are auditing whether a generated codebase delivers every
feature its user asked for. You will see the feature list followed by
the actual code, and you must report which features are present and
which are missing.

FEATURES THE USER REQUESTED:
{listing}

CODE THAT WAS GENERATED:
{code_blob}

For EACH feature, decide:
- "present"  — the feature is clearly implemented (HTML/JS/CSS evidence
   exists AND it actually does something)
- "missing"  — the code makes no real attempt at this feature
- "partial"  — the feature is started but obviously broken or stubbed.
   Treat partial as missing for downstream gating.

Respond with JSON ONLY in this exact shape:
{{
  "results": [
    {{ "feature": "<the feature label>", "status": "present" | "missing" | "partial", "evidence": "<one short phrase: file or selector that proves it>" }},
    ...
  ]
}}

Be strict — if you cannot point to specific evidence in the code,
the feature is missing.
"""


# Semantic-evidence rescue: the judge said "missing" but the code obviously
# contains the mechanism (Web Audio for sound features, textContent flips for
# mode labels, stroke-dasharray for progress rings, ...). Each entry is
# (label pattern, code pattern); a feature is rescued only when its label NAMES
# the mechanism AND the code contains a recognizable implementation — a stub
# (an empty `<div id="mode-label">` with no textContent flip) does not match,
# because the JS-side pattern is what has to be present. Case-insensitive.
_SEMANTIC_EVIDENCE_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"\b(audio|beep|tone|sound|chime|alarm)\b",
        r"(AudioContext|webkitAudioContext|createOscillator|"
        r"OscillatorNode|new\s+Audio\s*\(|AudioBufferSourceNode)",
    ),
    (
        r"\b(mode|status|state|phase)\s+label\b",
        r"(textContent|innerText|innerHTML)\s*=[^;]{0,200}?"
        r"['\"`][A-Z][A-Z _-]{1,30}['\"`]|"
        r"data-(mode|status|state|phase)\s*=",
    ),
    (
        r"\b(progress\s+ring|progress\s+circle|circular\s+progress|"
        r"ring\s+indicator)\b",
        r"(stroke-dasharray|stroke-dashoffset)",
    ),
    (
        r"\b(localstorage|persist|save\s+.*\bbrowser|store\s+"
        r".*\bbrowser|restore.*\breload)\b",
        r"localStorage\.(setItem|getItem|removeItem)",
    ),
    (
        r"\b(theme\s+toggle|dark\s+mode|light\s+mode|color\s+scheme)\b",
        r"(data-theme|\.dark\b|prefers-color-scheme|"
        r"classList\.toggle\s*\(\s*['\"]dark)",
    ),
    (
        r"\b(keyboard\s+shortcut|hotkey|keypress\s+handler|key\s+binding)\b",
        r"addEventListener\s*\(\s*['\"](keydown|keyup|keypress)['\"]",
    ),
    (
        r"\b(auto[-\s]?refresh|polling|live\s+update|tick|countdown)\b",
        r"(setInterval\s*\(|setTimeout\s*\([^,]+,\s*\d{2,})",
    ),
    (
        r"\b(reset|clear\s+all|restore\s+defaults|wipe)\b",
        r"(function\s+\w*[Rr]eset|=>\s*\{[^}]*reset|"
        r"addEventListener\s*\(\s*['\"]click['\"][^)]*[Rr]eset)",
    ),
    (
        r"\b(inline\s+error|friendly\s+error|validation\s+message|error\s+state)\b",
        r"(\.error|class=['\"][^'\"]*error|id=['\"][^'\"]*error)",
    ),
)


def search_semantic_evidence(label: str, code: str) -> str | None:
    """Return a short match string when the feature ``label`` names a known
    mechanism AND ``code`` contains a recognizable implementation of it — the
    false-negative escape hatch. ``None`` when no class matches (keep the LLM
    verdict). Conservative by construction: the code-side pattern must match,
    so a stub that only has the HTML id does not rescue."""
    if not label or not code:
        return None
    label_low = label.lower()
    for label_pat, code_pat in _SEMANTIC_EVIDENCE_PATTERNS:
        if not re.search(label_pat, label_low):
            continue
        m = re.search(code_pat, code, flags=re.IGNORECASE)
        if m:
            snippet = m.group(0)
            return snippet if len(snippet) <= 60 else snippet[:60] + "…"
    return None


def cross_validate(
    features: list[str],
    deterministic_missing: dict[str, list[str]],
    llm_results: list[dict[str, Any]],
    code_lower: str,
) -> tuple[list[str], list[dict[str, str]], int]:
    """Cross-validate Stage 1 markers against Stage 2 LLM verdicts.

    Returns:
        present_labels — features confirmed present
        missing_entries — list of {"feature","status","note"} for failures
        overrides_count — how many LLM "present" calls got demoted
    """
    llm_by_label: dict[str, tuple[str, str]] = {}
    for r in llm_results:
        if not isinstance(r, dict):
            continue
        label = (r.get("feature") or "").strip()
        status = (r.get("status") or "").lower()
        evidence = str(r.get("evidence") or "")
        if label:
            llm_by_label[label.lower()] = (status, evidence)

    present: list[str] = []
    missing: list[dict[str, str]] = []
    overrides = 0

    for label in features:
        key = label.lower()
        llm_status, evidence = llm_by_label.get(key, ("", ""))

        if label in deterministic_missing:
            # Stage 1 found no marker — rescue path requires concrete
            # LLM evidence the scanner can locate.
            if llm_status == "present" and evidence_visible_in_code(evidence, code_lower):
                present.append(label)
                continue
            markers_str = ", ".join(deterministic_missing[label][:3])
            if llm_status == "present":
                overrides += 1
                note = (
                    f"no code marker found (looked for: {markers_str}); "
                    + (
                        f"LLM evidence \"{evidence}\" not in code"
                        if evidence
                        else "LLM gave no concrete evidence"
                    )
                )
                missing.append({
                    "feature": label,
                    "status": "missing",
                    "note": note,
                })
            else:
                missing.append({
                    "feature": label,
                    "status": llm_status or "missing",
                    "note": evidence or f"no code marker found ({markers_str})",
                })
            continue

        # No deterministic miss — trust the LLM but require explicit "present".
        if llm_status == "present":
            present.append(label)
        elif search_semantic_evidence(label, code_lower):
            # False-negative rescue: Stage 1 found the marker but the judge said
            # missing/partial, yet the code demonstrably contains the named
            # mechanism (e.g. AudioContext for a "beep" feature). Flip to present.
            present.append(label)
        else:
            missing.append({
                "feature": label,
                "status": llm_status or "missing",
                "note": evidence,
            })

    return present, missing, overrides


def _result_from_deterministic_only(
    features: list[str],
    deterministic_missing: dict[str, list[str]],
    note: str,
) -> tuple[Verdict, str, dict[str, Any]]:
    """Fallback verdict when the LLM judge is unavailable / unparseable."""
    total = len(features)
    if not deterministic_missing:
        return (
            Verdict.passed,
            f"feature coverage ({total}/{total} markers found, fallback)",
            {
                "fallback": True,
                "note": note,
                "total": total,
                "present_count": total,
                "missing": [],
            },
        )
    missing_entries = [
        {"feature": label, "markers_checked": markers[:3]}
        for label, markers in list(deterministic_missing.items())[:8]
    ]
    return (
        Verdict.failed,
        (
            f"feature coverage fallback failed "
            f"({total - len(deterministic_missing)}/{total} markers found)"
        ),
        {
            "fallback": True,
            "note": note,
            "total": total,
            "present_count": total - len(deterministic_missing),
            "missing": missing_entries,
        },
    )


def _gather_features(brief: DesignDNA) -> list[str]:
    """Union of brief.features + features mined from brief.notes /
    brief.intent, deduped case-insensitively. Preserves order with the
    explicit features list first.
    """
    out: list[str] = []
    seen: set[str] = set()

    def _add(label: str) -> None:
        label = (label or "").strip()
        if not label:
            return
        key = re.sub(r"\s+", " ", label.lower()).strip()
        if key in seen:
            return
        seen.add(key)
        out.append(label)

    for f in brief.features or []:
        if isinstance(f, str):
            _add(f)
        elif isinstance(f, dict):  # tolerate {"name": "..."} dicts
            label = f.get("name") or f.get("description") or f.get("id") or ""
            if label:
                _add(str(label))

    for f in extract_brief_features(brief.notes or ""):
        _add(f)
    for f in extract_brief_features(brief.intent or ""):
        _add(f)

    return out


class FeatureCoverageCheck(CheckLayer):
    """Layer #21 — deterministic keyword scan + LLM judge for feature coverage."""

    NAME = "feature_coverage"
    KIND = LayerKind.hybrid
    APPLIES_TO = ("static_html", "node", "python")
    DESCRIPTION = (
        "Cross-validates LLM 'feature present/missing' verdicts against a "
        "deterministic keyword scan. The LLM cannot rubber-stamp features "
        "whose marker words appear nowhere in the code."
    )

    async def run_async(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        root = ctx.code_path
        if not root.is_dir():
            return self._skip("code_path is not a directory")

        if ctx.brief is None:
            return self._skip("No design brief — no feature contract to verify")

        features = _gather_features(ctx.brief)
        if not features:
            return self._skip("Brief has no features and notes mined no sentences")

        if ctx.llm_client is None:
            return self._skip(
                "No LLM client configured (use --no-llm to silence; "
                "feature_coverage cannot run without one)"
            )

        # Feature coverage judges the FRONTEND. Collect only frontend code
        # (no `.py`); if there is none, this is a non-frontend stack and the
        # layer does not apply — skip cleanly instead of false-failing on
        # backend code that has no UI features to find.
        code_blob = collect_code_blob(root, extensions=_FRONTEND_EXTS)
        if not code_blob.strip():
            return self._skip(
                "No frontend code to judge — feature coverage does not apply "
                "to a non-frontend stack"
            )

        code_lower = code_blob.lower()
        deterministic_missing = deterministic_missing_features(features, code_lower)

        prompt = _build_judge_prompt(features, code_blob)
        try:
            raw = await ctx.llm_client.judge(prompt, max_tokens=_MAX_TOKENS)
        except Exception as exc:
            outcome, summary, details = _result_from_deterministic_only(
                features, deterministic_missing,
                note=f"LLM judge unavailable: {type(exc).__name__}",
            )
            details["error"] = repr(exc)
            return self._result(outcome, summary=summary, start_time=start, details=details)

        verdict = parse_json_verdict(raw or "")
        if not verdict or not isinstance(verdict.get("results"), list):
            outcome, summary, details = _result_from_deterministic_only(
                features, deterministic_missing,
                note="LLM judge returned unparseable JSON",
            )
            details["raw_tail"] = (raw or "")[-500:]
            return self._result(outcome, summary=summary, start_time=start, details=details)

        present, missing, overrides = cross_validate(
            features, deterministic_missing, verdict["results"], code_lower,
        )

        total = len(features)
        details = {
            "fallback": False,
            "total": total,
            "present_count": len(present),
            "present": present,
            "missing": missing[:20],
            "missing_total": len(missing),
            "llm_overrides": overrides,
        }

        if missing:
            return self._result(
                Verdict.failed,
                summary=(
                    f"feature coverage: {len(missing)}/{total} feature(s) "
                    f"missing or partial"
                ),
                start_time=start,
                details=details,
                override_fired=overrides > 0,
            )

        return self._result(
            Verdict.passed,
            summary=f"feature coverage: {total}/{total} present",
            start_time=start,
            details=details,
        )

    def run(self, ctx: ValidationContext) -> LayerResult:  # pragma: no cover
        import asyncio
        return asyncio.run(self.run_async(ctx))


__all__ = [
    "FeatureCoverageCheck",
    "feature_keyword_markers",
    "extract_brief_features",
    "evidence_visible_in_code",
    "deterministic_missing_features",
    "cross_validate",
]
