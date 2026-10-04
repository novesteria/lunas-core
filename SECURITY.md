# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| Latest minor release | ✅ |
| Previous minor release | ✅ (security fixes only, for 6 months) |
| Older | ❌ |

## What counts as a security issue

Lunas runs build and test commands against untrusted code. The threat
model assumes the code being validated may be malicious.

Reportable security issues include:

- **Sandbox escape** — code under validation gaining access to the host
  environment, credentials, or network resources it should not reach.
- **Subprocess env leakage** — the env-scrubbing layer failing to remove
  a sensitive environment variable before launching the subprocess.
- **Supply-chain bypass** — code under validation managing to run
  install-time scripts (`preinstall` / `postinstall`) despite the
  `--ignore-scripts` flag.
- **Timeout bypass** — code under validation running longer than the
  configured per-command timeout (default 300s).
- **Prompt injection that escapes the boundary markers** — user-supplied
  text being interpreted as instructions by the LLM judge despite
  sanitization.

Reportable issues do **not** include:

- The validator giving an incorrect verdict on a piece of code. This is
  an accuracy bug — open a regular issue with a reproducible test case.
- A check layer being slow. Open a regular performance issue.
- A configuration choice you disagree with. Open a discussion.

## Reporting a vulnerability

**Do not open a public issue for security reports.**

Email [security@novesteria.com](mailto:security@novesteria.com) with:

1. A description of the vulnerability.
2. Steps to reproduce, or a proof-of-concept.
3. The impact you've observed or predicted.
4. Your name and how you'd like to be credited (or "anonymous").

We will acknowledge receipt within 5 business days, provide an initial
assessment within 14 days, and aim to issue a fix within 60 days for
critical issues.

## Disclosure policy

Once a fix is released, we will:

1. Publish a GitHub Security Advisory describing the vulnerability,
   affected versions, and the fix.
2. Credit the reporter (unless they prefer anonymity).
3. Update CHANGELOG.md.

We follow a 90-day coordinated disclosure window from the first report.
If 90 days pass without a fix, the reporter may disclose publicly with
our acknowledgment.

## Out of scope

The Lunas validator itself is open source and runs locally. We do not
operate a hosted version. Issues with Novesteria's hosted products should be reported to
their respective security contacts.

## About

Lunas is maintained by [Novesteria](https://novesteria.com). For
general questions, contact [hello@novesteria.com](mailto:hello@novesteria.com).
