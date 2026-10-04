# 04 — import case mismatch (TypeScript)

**Stack:** node (TypeScript)
**Layer:** `import_case_consistency`
**Expected verdict:** FAIL

## Input

A small TypeScript project with two source files. `userService.ts`
exports `userService` (camelCase) and `UserCard` (PascalCase).
`main.ts` imports `{ user_service }` (snake_case) and
`{ Usercard }` (lowercased second letter).

## Bug

Both compile-target files exist and module specifiers resolve, so a
plain "does the file exist" check passes. The
`import_case_consistency` layer additionally verifies the imported
NAME matches the exported NAME under a case-normalised comparison.
It reports each mismatch with the actual exported identifier so the
fix is one line.

This is the failure mode that survives macOS / Windows
(case-insensitive filesystems) and breaks on a Linux deploy.

## Files

- `brief.json` — generic editorial dashboard
- `input/code/userService.ts` — exports `userService` + `UserCard`
- `input/code/main.ts` — imports `{ user_service, Usercard }`
- `expected.json` — passed=false, `import_case_consistency` flags both
