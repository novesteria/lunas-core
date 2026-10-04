---
name: Feature request / new check layer
about: Propose a new check layer or improvement to an existing one
title: '[Feature] '
labels: enhancement, needs-discussion
assignees: ''
---

## What problem does this solve

A specific class of bug or AI-generated-code failure mode that current
layers don't catch. Cite a real example if you can — synthetic ones
are accepted but real ones are better.

## Proposed layer type

- [ ] **Deterministic** — AST check, regex, build runner, test runner, etc.
      Layer fails or passes based on observable code state, no LLM.
- [ ] **Hybrid** — LLM judgment with a deterministic override (override
      must be able to fail the layer regardless of LLM verdict).
- [ ] **LLM-as-judge** — Pure model judgment. We only accept these when
      no deterministic or hybrid alternative exists, and reviewers will
      push hard to find one.

## Sketch of how it would work

Rough algorithm or pseudocode. The pipeline is structured around
"layers", so describe what your layer reads, what it checks, and what
it returns.

## Bench case

Every new layer needs a corresponding case in `lunas-bench/cohort/`
that demonstrates the failure it catches. Sketch it here:

```
lunas-bench/cohort/<your-case-name>/
├── input/             # AI-generated code that should fail without your layer
├── expected.json      # The verdict your layer should produce
└── README.md          # Why this case matters
```

## Stack scope

Which stacks does this apply to?

- [ ] Python
- [ ] Node.js / TypeScript / JavaScript
- [ ] Static HTML
- [ ] Other (specify)
- [ ] Language-agnostic

## Alternatives considered

If there's an existing tool (eslint rule, mypy plugin, etc.) that does
this, why isn't it sufficient? Lunas aggregates tools where it makes
sense — we don't reimplement things that already work.

## Anything else

Performance impact, false-positive risk, configurability needs.
