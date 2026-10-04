"""``lunas`` command-line entry point.

Usage:
    lunas check ./path                       # deterministic + LLM (needs API key)
    lunas check ./path --no-llm              # CI-friendly, no API key needed
    lunas check ./path --brief brief.json    # design fidelity + feature coverage layers
    lunas check ./path --json report.json    # machine-readable output
    lunas check ./path --exit-on-fail        # non-zero exit when verdict is FAIL

Defaults:
- Output to stdout in human-readable form
- Exit code 0 even on FAIL (so CI scripts can differentiate "tool ran
  but found problems" from "tool crashed"); use --exit-on-fail to
  return 1 on validation failure.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from lunas import __version__, validate
from lunas.design_dna import load_brief
from lunas.llm_client import AnthropicClient
from lunas.result import Verdict


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lunas",
        description="Lunas — a deterministic validator for AI-generated code.",
        epilog="Documentation: https://github.com/novesteria/lunas-core",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"lunas-validator {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser(
        "check",
        help="Validate a directory of code.",
    )
    check.add_argument(
        "path",
        type=Path,
        help="Directory containing the code to validate.",
    )
    check.add_argument(
        "--brief",
        type=Path,
        default=None,
        help="Path to a brief.json (DesignDNA). When omitted, LLM-judge "
             "and feature-coverage layers are skipped.",
    )
    check.add_argument(
        "--json",
        type=Path,
        default=None,
        metavar="PATH",
        help="Write the full report to a JSON file (alongside stdout).",
    )
    check.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM-using layers (design fidelity, feature coverage). "
             "No API key required; CI-friendly.",
    )
    check.add_argument(
        "--exit-on-fail",
        action="store_true",
        help="Exit with code 1 when the validation verdict is FAIL. "
             "Default is to exit 0 unless the tool itself crashed.",
    )
    check.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-layer detail to stdout.",
    )

    return parser


async def _run_check(args: argparse.Namespace) -> int:
    code_path: Path = args.path
    if not code_path.is_dir():
        print(f"error: {code_path} is not a directory", file=sys.stderr)
        return 2

    brief = None
    if args.brief is not None:
        try:
            brief = load_brief(args.brief)
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: brief load failed: {exc}", file=sys.stderr)
            return 2

    llm_client = None
    if not args.no_llm:
        try:
            llm_client = AnthropicClient() if AnthropicClient is not None else None
        except (ImportError, ValueError) as exc:
            print(
                f"warning: LLM client unavailable ({exc}); falling back to --no-llm",
                file=sys.stderr,
            )

    report = await validate(
        str(code_path),
        brief=brief,
        llm_client=llm_client,
        no_llm=args.no_llm,
    )

    # ---- output ----
    print(report.summary())
    if args.verbose:
        for layer in report.layers:
            mark = {
                Verdict.passed: "✓",
                Verdict.failed: "✗",
                Verdict.skipped: "·",
                Verdict.error: "!",
            }[layer.verdict]
            print(f"  {mark} {layer.name:<35} {layer.summary}")

    if args.json is not None:
        report.to_file(args.json)
        print(f"  · report written to {args.json}", file=sys.stderr)

    if args.exit_on_fail and not report.passed:
        return 1
    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "check":
        exit_code = asyncio.run(_run_check(args))
        sys.exit(exit_code)
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
