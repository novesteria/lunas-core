# 15 — hook return drift

**Stack:** node (React 18 + TypeScript)
**Layer:** `hook_destructure_consistency`
**Expected verdict:** FAIL

## Input

A React coin-dashboard. `src/hooks/useCoins.ts` defines a custom hook
whose last `return` statement is `return { coins, isLoading }`.
`src/Dashboard.tsx` consumes it with
`const { coins, isLoading, lastUpdated } = useCoins();` and calls
`formatDate(lastUpdated)`.

## Bug

The consumer destructures `lastUpdated`, but the hook does not return
that field. At runtime `lastUpdated` is `undefined`, and `formatDate`
crashes when it calls `.toLocaleString()`. `tsc` would catch this only
when the hook has an explicit return-type annotation — this one
doesn't. The static layer extracts the last top-level return object's
keys from every `use*` hook (function declaration, concise arrow,
block-body arrow), then scans `const { … } = useX(…)` consumers and
flags any destructured name not in the returned shape.

## Files

- `brief.json`
- `input/package.json`
- `input/src/hooks/useCoins.ts` — returns `{ coins, isLoading }`
- `input/src/Dashboard.tsx` — destructures `lastUpdated`
- `input/src/App.tsx`
- `expected.json`
