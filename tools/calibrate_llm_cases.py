"""Run the LLM-judge layers against the bench cases that need calibration.

Reads `.env` locally (which is git-ignored), loads
``ANTHROPIC_API_KEY`` into the process environment, and runs the full
``lunas`` pipeline against each case directory. Writes the actual
report to ``cohort/<case>/actual_llm.json`` for inspection.

This script is for local calibration runs only — it never prints or
commits the API key.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    """Read .env in the repo root and populate ``os.environ`` for keys
    not already set. Key values are NEVER printed.
    """
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        sys.stderr.write(f"error: {env_path} not found\n")
        sys.exit(2)
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key and value:
            os.environ.setdefault(key, value)


_load_env()

# Imports must come AFTER env load so AnthropicClient sees the key.
from lunas import validate  # noqa: E402
from lunas.design_dna import load_brief  # noqa: E402
from lunas.llm_client import AnthropicClient  # noqa: E402
from lunas.result import Verdict  # noqa: E402


CASES_TO_CALIBRATE = (
    "16-typography-substitution",
    "17-density-violation",
    "18-missing-csv-export",
    "19-missing-dark-toggle",
)


async def run_one(case_slug: str, client: AnthropicClient) -> None:
    case_dir = REPO_ROOT / "lunas-bench" / "cohort" / case_slug
    brief = load_brief(case_dir / "brief.json")
    print(f"\n=== {case_slug} ===")

    report = await validate(
        str(case_dir / "input"),
        brief=brief,
        llm_client=client,
    )
    actual_path = case_dir / "actual_llm.json"
    report.to_file(actual_path)
    print(f"overall_passed = {report.passed}")

    for layer in report.layers:
        if layer.name not in ("design_fidelity", "feature_coverage"):
            continue
        if layer.verdict == Verdict.skipped:
            continue
        print(f"\n  layer: {layer.name}")
        print(f"  verdict: {layer.verdict.value}")
        print(f"  summary: {layer.summary}")
        print(f"  override_fired: {layer.override_fired}")
        d = layer.details
        if "overall_score" in d:
            print(f"  overall_score: {d['overall_score']}/10")
        if "dimensions" in d and isinstance(d["dimensions"], list):
            for dim in d["dimensions"]:
                if isinstance(dim, dict):
                    name = dim.get("name", "?")
                    score = dim.get("score", "?")
                    comment = str(dim.get("comment", ""))[:120]
                    print(f"    {name}: {score}/10  ({comment})")
        if "forced_fail" in d:
            print(f"  forced_fail: {d['forced_fail']}")
        if "missing" in d and isinstance(d["missing"], list) and d["missing"]:
            print("  missing list:")
            for m in d["missing"][:5]:
                if isinstance(m, str):
                    print(f"    - {m[:140]}")
                else:
                    print(f"    - {m}")
        if "llm_overrides" in d:
            print(f"  llm_overrides: {d['llm_overrides']}")
        if "present" in d:
            print(f"  present features: {d['present']}")


async def main() -> None:
    client = AnthropicClient()
    for slug in CASES_TO_CALIBRATE:
        try:
            await run_one(slug, client)
        except Exception as exc:
            print(f"  ERROR running {slug}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
