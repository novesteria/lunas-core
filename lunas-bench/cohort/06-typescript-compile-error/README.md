# 06 — typescript compile error

**Stack:** node (React 18 + TypeScript + Vite)
**Layer:** `tsc`
**Expected verdict:** FAIL

## Input

A React + TypeScript user-profile component. `src/types.ts` declares
`interface UserProfile { id, name, email, joinedAt }`. `src/UserCard.tsx`
reads `user.fullName`.

## Bug

`tsc --noEmit` fails with TS2339: property `fullName` does not exist
on `UserProfile`. Static layers (imports, deps, prop consistency) all
pass; only the TypeScript compiler catches the field-name divergence.

## Files

- `brief.json`
- `input/package.json`
- `input/tsconfig.json`
- `input/index.html`
- `input/src/types.ts`
- `input/src/UserCard.tsx` — reads `user.fullName`
- `input/src/App.tsx`
- `input/src/main.tsx`
- `expected.json`
