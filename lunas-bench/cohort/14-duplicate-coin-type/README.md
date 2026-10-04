# 14 — duplicate Coin type with conflicting shapes

**Stack:** node (React 18 + TypeScript)
**Layer:** `duplicate_type_declarations`
**Expected verdict:** FAIL

## Input

A React portfolio page. `src/types.ts` declares
`interface Coin { id, symbol, name, price, change_24h }`.
`src/components/CoinRow.tsx` redeclares `interface Coin { name, value }`
locally. `src/api.ts` returns canonical `Coin[]`; `App.tsx` passes
those rows to `CoinRow`.

## Bug

The same type name `Coin` is declared in two different files with
different member sets. TS2300 (duplicate declaration) does not fire
because the declarations live in different scopes — both files
compile. At runtime, `CoinRow` uses its local shape and silently
drops `id`, `symbol`, `price`, and `change_24h`. The
`duplicate_type_declarations` layer walks every `interface`/`type`
declaration, groups by name, and flags names with multiple distinct
member-sets across files (matching same-shape merges are excluded).

## Files

- `brief.json`
- `input/package.json`
- `input/src/types.ts` — canonical `Coin`
- `input/src/api.ts`
- `input/src/components/CoinRow.tsx` — local redeclaration of `Coin`
- `input/src/App.tsx`
- `expected.json`
