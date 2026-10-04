// Deliberate Brand Audit #14 bug: the imports below use the wrong
// casing. `userService.ts` exports `userService` (camelCase) and
// `UserCard` (PascalCase), but here we import:
//   - `user_service` (snake_case)
//   - `Usercard`     (lowercase 'c')
//
// `_check_named_import_consistency` would already flag both as
// "name not exported." `_check_import_case_consistency` flags them
// MORE specifically as case mismatches and surfaces the actual
// exported name so the fix is mechanical.

import { user_service } from './userService';
import { Usercard } from './userService';

async function main() {
  const users: Usercard[] = await user_service.listUsers();
  console.log(`Loaded ${users.length} users.`);
}

main().catch((e) => {
  console.error('failed:', e);
  process.exit(1);
});
