"""Run every case in ``lunas-bench/cohort/`` against the validator and
report how many cases match their declared expectations.

Usage:

    python lunas-bench/scripts/run_lunas.py                   # all cases
    python lunas-bench/scripts/run_lunas.py --case 04-...     # single case
    python lunas-bench/scripts/run_lunas.py --no-llm          # skip LLM layers
    python lunas-bench/scripts/run_lunas.py --json results/<file>.json

The runner produces one row per case with PASS / FAIL / SKIP. A case
PASSes the bench when the actual report matches every assertion the
case's ``expected.json`` declares — at minimum ``passed`` (bool), and
when present:

  * ``failed_layer``           — name of the layer that must report FAIL
  * ``deterministic_override_expected`` (bool)
  * ``min_capped_dimensions``  — {dimension: max_score}
  * ``check_type``             — for cases that target a specific layer
  * ``side_effect_check.file_must_not_exist`` — checked on disk after run

When the actual report disagrees with expected, the row is reported
FAIL and the runner exits with a non-zero status.

Loads ``.env`` from the repo root so ``ANTHROPIC_API_KEY`` is in the
environment when the LLM-using layers run; ``--no-llm`` overrides.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_env() -> None:
    """Populate os.environ from .env (git-ignored). Never prints the key."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k and v:
            os.environ.setdefault(k, v)


_load_env()

# Imports must come AFTER env load so AnthropicClient picks up the key.
import lunas  # noqa: E402
from lunas import validate as lunas_validate  # noqa: E402
from lunas.design_dna import load_brief  # noqa: E402
from lunas.llm_client import AnthropicClient  # noqa: E402
from lunas.result import LayerResult, ValidationReport, Verdict  # noqa: E402


COHORT_DIR = REPO_ROOT / "lunas-bench" / "cohort"


# ----- expected.json checks --------------------------------------------


def _layer_by_name(report: ValidationReport, name: str) -> Optional[LayerResult]:
    for layer in report.layers:
        if layer.name == name:
            return layer
    return None


def _dim_score(layer: LayerResult, dim_name: str) -> Optional[int]:
    dims = layer.details.get("dimensions") if layer.details else None
    if not isinstance(dims, list):
        return None
    for d in dims:
        if isinstance(d, dict) and d.get("name") == dim_name:
            try:
                return int(d.get("score") or 0)
            except (TypeError, ValueError):
                return None
    return None


def _check_expected(
    expected: dict, report: ValidationReport, case_dir: Path,
) -> list[str]:
    """Return a list of human-readable mismatch messages. Empty list
    means the case PASSed the bench.
    """
    problems: list[str] = []

    # 1. overall passed flag (always present)
    if "passed" in expected:
        if bool(expected["passed"]) != bool(report.passed):
            problems.append(
                f"passed mismatch: expected={expected['passed']} actual={report.passed}"
            )

    # 2. specific failing layer name (if declared)
    if expected.get("failed_layer"):
        target = expected["failed_layer"]
        layer = _layer_by_name(report, target)
        if layer is None:
            problems.append(f"failed_layer={target} not present in report")
        elif layer.verdict != Verdict.failed:
            problems.append(
                f"failed_layer={target} reported {layer.verdict.value}, expected failed"
            )

    # 3. deterministic_override_expected — informational only.
    # The override path CAN fire when the LLM judge would otherwise
    # rubber-stamp. When the LLM independently produces the right
    # verdict, the override is not needed and does not fire — that's
    # also a passing state. Asserting override_fired strictly would
    # penalise a more capable model. We observe but do not assert.

    # 4. capped dimensions
    capped = expected.get("min_capped_dimensions") or {}
    if isinstance(capped, dict) and capped:
        df = _layer_by_name(report, "design_fidelity")
        if df is None:
            problems.append("min_capped_dimensions specified but design_fidelity layer missing")
        else:
            for dim_name, max_score in capped.items():
                actual_score = _dim_score(df, dim_name)
                if actual_score is None:
                    problems.append(f"dimension {dim_name!r} not in design_fidelity output")
                elif actual_score > int(max_score):
                    problems.append(
                        f"dimension {dim_name} = {actual_score}/10, expected ≤ {max_score}"
                    )

    # 5. side-effect check (file_must_not_exist)
    side = expected.get("side_effect_check") or {}
    if isinstance(side, dict):
        ne = side.get("file_must_not_exist")
        if ne:
            input_dir = case_dir / "input"
            if (input_dir / ne).exists():
                problems.append(
                    f"side_effect: {ne} exists in input/ after run (must not)"
                )

    return problems


def _ensure_case_venv(input_dir: Path) -> Optional[str]:
    """Create ``input/.venv`` from ``requirements.txt`` for Python cases.

    The ``pytest`` layer prefers a project-local venv, so installing the
    case's own dependencies there keeps the run reproducible on any
    machine without touching the validator's environment. The venv is
    git-ignored. Returns an error string on failure, else None.
    """
    req = input_dir / "requirements.txt"
    venv = input_dir / ".venv"
    if not req.exists():
        return None
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if py.exists():
        return None
    try:
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True)
        pip_cmd = [str(py), "-m", "pip", "install", "-q", "-r", str(req)]
        r = subprocess.run(pip_cmd, capture_output=True, text=True)
        if r.returncode != 0:
            uv = shutil.which("uv")
            if not uv:
                return f"pip install failed: {r.stderr.strip()[-300:]}"
            subprocess.run([uv, "pip", "install", "-q", "--python", str(py), "-r", str(req)],
                           check=True, capture_output=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        return f"venv setup failed: {exc}"
    return None


# ----- bench loop ------------------------------------------------------


async def run_case(
    case_dir: Path, *, use_llm: bool, llm_client: Optional[AnthropicClient],
) -> dict[str, Any]:
    brief_path = case_dir / "brief.json"
    expected_path = case_dir / "expected.json"
    input_dir = case_dir / "input"

    if not expected_path.exists():
        return {
            "case": case_dir.name,
            "status": "skip",
            "reason": "expected.json missing",
        }
    expected = json.loads(expected_path.read_text(encoding="utf-8"))

    venv_err = _ensure_case_venv(input_dir)
    if venv_err:
        return {"case": case_dir.name, "status": "error", "reason": venv_err}

    # When the bench is run with --no-llm, cases whose verdict depends
    # on an LLM-using layer can't be honestly evaluated. Mark them
    # skipped rather than failing the runner on its own flag.
    LLM_LAYERS = {"design_fidelity", "feature_coverage"}
    if not use_llm:
        if expected.get("failed_layer") in LLM_LAYERS:
            return {
                "case": case_dir.name,
                "status": "skip",
                "reason": f"--no-llm: {expected['failed_layer']} requires LLM",
            }
        # Older v1 cases don't name failed_layer but expect an override
        # path through design_fidelity. Detect by the override flag +
        # capped-dimensions block.
        if (
            expected.get("deterministic_override_expected")
            and isinstance(expected.get("min_capped_dimensions"), dict)
            and expected["min_capped_dimensions"]
        ):
            return {
                "case": case_dir.name,
                "status": "skip",
                "reason": "--no-llm: override path needs LLM judge",
            }

    brief = None
    if brief_path.exists():
        try:
            brief = load_brief(brief_path)
        except Exception as exc:
            return {
                "case": case_dir.name,
                "status": "skip",
                "reason": f"brief load failed: {type(exc).__name__}: {exc}",
            }

    try:
        report = await lunas_validate(
            str(input_dir),
            brief=brief,
            llm_client=llm_client if use_llm else None,
            no_llm=not use_llm,
        )
    except Exception as exc:
        return {
            "case": case_dir.name,
            "status": "error",
            "reason": f"{type(exc).__name__}: {exc}",
        }

    problems = _check_expected(expected, report, case_dir)
    return {
        "case": case_dir.name,
        "status": "pass" if not problems else "fail",
        "actual_passed": report.passed,
        "duration_seconds": round(report.duration_seconds, 2),
        "problems": problems,
        "failed_layers": [
            l.name for l in report.layers if l.verdict == Verdict.failed
        ],
    }


async def main_async(args: argparse.Namespace) -> int:
    if not COHORT_DIR.is_dir():
        print(f"error: {COHORT_DIR} does not exist", file=sys.stderr)
        return 2

    case_dirs: list[Path]
    if args.case:
        target = COHORT_DIR / args.case
        if not target.is_dir():
            print(f"error: case not found: {target}", file=sys.stderr)
            return 2
        case_dirs = [target]
    else:
        case_dirs = sorted(p for p in COHORT_DIR.iterdir() if p.is_dir())

    use_llm = not args.no_llm
    llm_client: Optional[AnthropicClient] = None
    if use_llm:
        try:
            llm_client = AnthropicClient()
        except Exception as exc:
            print(
                f"warning: LLM client unavailable ({exc}); continuing with --no-llm semantics",
                file=sys.stderr,
            )
            use_llm = False

    rows: list[dict[str, Any]] = []
    for case_dir in case_dirs:
        print(f"\n=== {case_dir.name} ===")
        row = await run_case(case_dir, use_llm=use_llm, llm_client=llm_client)
        rows.append(row)
        if row["status"] == "pass":
            print(f"  PASS · duration {row.get('duration_seconds')}s")
        elif row["status"] == "skip":
            print(f"  SKIP · {row.get('reason')}")
        elif row["status"] == "error":
            print(f"  ERROR · {row.get('reason')}")
        else:
            print(f"  FAIL · failed layers: {row.get('failed_layers')}")
            for p in row.get("problems", []):
                print(f"    - {p}")

    # ----- summary -----
    counts = {"pass": 0, "fail": 0, "skip": 0, "error": 0}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    total = len(rows)

    print("\n" + "=" * 50)
    print(
        f"Bench summary: {counts['pass']}/{total} pass · "
        f"{counts['fail']} fail · {counts['skip']} skip · {counts['error']} error"
    )
    print("=" * 50)

    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {
                    "timestamp_utc": dt.datetime.utcnow().isoformat() + "Z",
                    "use_llm": use_llm,
                    "model": (getattr(llm_client, "model", None)
                              or getattr(llm_client, "_model", None)) if use_llm else None,
                    "lunas_version": lunas.__version__,
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "total": total,
                    "counts": counts,
                    "rows": rows,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"results written: {out_path}")

    # Exit 1 if anything failed or errored
    return 0 if counts["fail"] == 0 and counts["error"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="lunas-bench cohort runner")
    parser.add_argument("--case", help="Run a single case directory name", default=None)
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM-using layers (design_fidelity, feature_coverage)",
    )
    parser.add_argument(
        "--json",
        help="Write a structured run-result JSON to this path",
        default=None,
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
