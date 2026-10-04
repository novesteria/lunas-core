## What does this PR do

One or two sentences. Be specific.

## Linked issue

Closes #<number>

## Type of change

- [ ] New check layer (deterministic / hybrid / llm-judge)
- [ ] Bug fix in existing layer
- [ ] New stack support
- [ ] Bench cohort case
- [ ] Documentation
- [ ] Build / CI / project structure
- [ ] Refactor (no behavior change)

## Bench result

```
$ python lunas-bench/scripts/run_lunas.py

[paste bench output here — required for layer + stack changes]
```

For docs / CI / refactor PRs, write "n/a" and explain why.

## Checks

- [ ] If this is a new layer, it includes a bench cohort case in `lunas-bench/cohort/`
- [ ] If this is a new stack, the validator runs in a sandboxed subprocess with
      env-scrub and `--ignore-scripts` (matching the existing stacks)
- [ ] If this is a hybrid or llm-judge layer, the deterministic override is
      documented in METHODOLOGY.md
- [ ] Tests pass locally (`pytest`)
- [ ] `lunas-bench` passes locally (no regression)
- [ ] DCO signed (`git commit -s`)
- [ ] CHANGELOG.md updated (for non-trivial changes)

## Anything reviewers should know

Tricky parts, design choices that could have gone another way,
follow-ups you didn't do in this PR.
