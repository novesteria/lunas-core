"""Sandboxed subprocess runner.

Validator layers that need to invoke ``npm install``, ``tsc``,
``pytest``, ``node --check`` etc. go through ``run_cmd``. The runner:

1. **Scrubs the environment** of credentials before launching the
   subprocess. Keys / tokens / secrets visible to the parent process
   do not leak to the code under validation.
2. **Enforces a timeout** (default 300s) so a hung target can't block
   the entire pipeline indefinitely.
3. **Captures stdout + stderr** for the layer's verdict — failures are
   reported with the actual command output, not a generic message.

For Node, layers should pass ``--ignore-scripts`` flags to ``npm`` to
neutralize ``preinstall`` / ``postinstall`` supply-chain attacks. This
is the layer's responsibility; the runner only provides the env scrub.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path

# Environment variable name patterns that look like credentials.
# Matched case-insensitively against env var keys; any match → variable
# is stripped from the subprocess env.
_SECRET_PATTERN = re.compile(
    r"(KEY|SECRET|TOKEN|PASSWORD|PASS|PWD|AUTH|CREDENTIAL|"
    r"ANTHROPIC_|GITHUB_|GOOGLE_|JWT_|DATABASE_URL|"
    r"SUPABASE_|STRIPE_|AWS_|AZURE_)",
    re.IGNORECASE,
)


def scrub_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of ``env`` (default: ``os.environ``) with credential
    variables removed.

    Variables matching ``_SECRET_PATTERN`` in their key name are filtered
    out. Used to construct the env for any subprocess that runs untrusted
    code under validation.
    """
    source = env if env is not None else os.environ
    return {k: v for k, v in source.items() if not _SECRET_PATTERN.search(k)}


@dataclass(frozen=True)
class CmdResult:
    """The outcome of one subprocess invocation."""

    returncode: int
    """Process exit code; 0 = success, non-zero = failure."""

    stdout: str
    """Captured stdout (utf-8 decoded, errors ignored)."""

    stderr: str
    """Captured stderr (utf-8 decoded, errors ignored)."""

    duration_seconds: float
    """Wall-clock duration."""

    timed_out: bool
    """True if the command was killed by the timeout."""


async def run_cmd(
    argv: list[str],
    *,
    cwd: str | Path,
    timeout: int = 300,
    env: dict[str, str] | None = None,
) -> CmdResult:
    """Run a subprocess with a scrubbed environment and a timeout.

    Args:
        argv: Argument list — first element is the program, rest are args.
            Lunas intentionally does NOT pass ``shell=True``; commands
            are exec'd directly.
        cwd: Working directory for the subprocess.
        timeout: Maximum wall-clock seconds before SIGKILL. Default 300.
        env: Optional env dict to scrub. Defaults to ``os.environ``.

    Returns:
        ``CmdResult`` with returncode, stdout, stderr, duration, and
        whether the timeout fired.

    The function never raises for non-zero exit codes — those are
    normal validator outcomes. It does raise ``FileNotFoundError`` if
    ``argv[0]`` isn't on PATH (this is a setup error, not a validation
    outcome).
    """
    import time
    start = time.monotonic()
    scrubbed_env = scrub_env(env)

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            env=scrubbed_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        # argv[0] is not on PATH — this is a developer/CI error, not a
        # validation outcome. Propagate.
        raise

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout,
        )
        timed_out = False
    except TimeoutError:
        process.kill()
        stdout_bytes, stderr_bytes = await process.communicate()
        timed_out = True

    return CmdResult(
        returncode=process.returncode if process.returncode is not None else -1,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        duration_seconds=time.monotonic() - start,
        timed_out=timed_out,
    )


__all__ = ["run_cmd", "scrub_env", "CmdResult"]
