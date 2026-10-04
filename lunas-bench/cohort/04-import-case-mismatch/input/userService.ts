// Canonical Brand Audit #14 case: this file exports `userService`
// (camelCase) and `UserCard` (PascalCase). A peer file imports them
// with the WRONG casing — see main.ts.

export interface UserCard {
  id: string;
  name: string;
  email: string;
  joinedAt: string;
}

export const userService = {
  async fetchUser(id: string): Promise<UserCard> {
    const r = await fetch(`/api/users/${id}`);
    return (await r.json()) as UserCard;
  },
  async listUsers(): Promise<UserCard[]> {
    const r = await fetch('/api/users');
    return (await r.json()) as UserCard[];
  },
};
