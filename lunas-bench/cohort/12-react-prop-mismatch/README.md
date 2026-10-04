# 12 — React prop name mismatch

**Stack:** node (React 18 + TypeScript, no tsconfig)
**Layer:** `react_prop_consistency`
**Expected verdict:** FAIL

## Input

A React crypto dashboard. `src/CryptoCard.tsx` declares
`interface CryptoCardProps { coin: CryptoCurrency }`. `src/CryptoGrid.tsx`
renders three cards with `<CryptoCard crypto={c} />`. No `tsconfig.json`
ships in the input.

## Bug

The JSX call site passes a prop named `crypto`, but the component's
declared Props only contain `coin`. At runtime the component receives
`coin: undefined` and crashes on `coin.price.toFixed()`. The
`react_prop_consistency` layer scans every JSX open tag, reads the
component's declared Props interface, subtracts built-in JSX attributes
(`key`, `className`, `on*`, etc.), and flags the unknown `crypto`.

The case ships without `tsconfig.json`, so the `tsc` layer skips. The
static layer catches the mismatch on its own.

## Files

- `brief.json`
- `input/package.json` — no tsconfig.json
- `input/src/types.ts`
- `input/src/CryptoCard.tsx` — declares `interface CryptoCardProps { coin }`
- `input/src/CryptoGrid.tsx` — passes `<CryptoCard crypto={c} />`
- `input/src/App.tsx`
- `expected.json`
