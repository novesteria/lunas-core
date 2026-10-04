# Contributing to Lunas

Thank you for considering a contribution.

## Code of Conduct

Participation is governed by the [Code of Conduct](./CODE_OF_CONDUCT.md).
Read it before contributing.

## How you can help

### Run the bench, share results

`lunas-bench/` is a reproducible cohort of validation cases. Run it
against your own AI-generated code and open a discussion or PR with
what you found. Real failure modes inform new check layers.

### Add a check layer

Lunas ships layers under `lunas/checks/`. New layers should:

- Be deterministic where possible. LLM judgment is allowed only with
  a deterministic override that can fail the layer regardless of the
  model's verdict.
- Ship with a bench case under `lunas-bench/cohort/` that
  demonstrates the failure mode the layer catches.
- Declare a `KIND` (`deterministic`, `hybrid`, or `llm_judge`) so the
  pipeline knows how to schedule it.

### Add a stack

Today: Python, Node.js / TypeScript / JavaScript, static HTML.

A new stack needs:

- A detection helper in `lunas/stack_detection.py`.
- One or more check layers in `lunas/checks/` covering install, type
  check (if applicable), and test runner.
- A bench cohort case demonstrating the failure mode.
- Subprocess calls routed through `lunas.subprocess_runner.run_cmd`
  (env scrub + timeout + `--ignore-scripts` for package managers).

### Improve the docs

`METHODOLOGY.md` and `docs/` are first-class. Clarity improvements,
worked examples, and translations are welcome.

## What we won't accept

- Layers that add LLM judgment without a deterministic override.
- Stack support without a bench cohort case.
- Refactors without a reproducible problem they solve.

## Workflow

1. Open an issue describing the problem before writing a PR. Many
   "improvements" turn out to be opinion; surfacing them early saves
   review time.
2. Branch from `main` as `<type>/<short-description>` —
   e.g. `feat/go-stack` or `fix/import-resolver`.
3. Keep PRs focused. One layer per PR, one bug fix per PR.
4. Run `pytest` and the bench locally. CI runs both; local runs
   surface failures faster.
5. New behavior needs a test. Bench cohort cases count.
6. Sign your commits (`git commit -s`).

## License

By contributing, you agree your contributions are licensed under
[Apache License 2.0](./LICENSE).

## Questions

Open a [discussion](https://github.com/novesteria/lunas-core/discussions)
or email [hello@novesteria.com](mailto:hello@novesteria.com).
