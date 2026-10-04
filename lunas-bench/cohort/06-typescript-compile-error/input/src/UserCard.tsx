import type { UserProfile } from './types';

interface UserCardProps {
  user: UserProfile;
}

function formatJoined(date: string): string {
  const d = new Date(date);
  return `Joined ${d.toLocaleString('default', { month: 'long', year: 'numeric' })}`;
}

export function UserCard({ user }: UserCardProps) {
  return (
    <article className="user-card">
      <h2>{user.fullName}</h2>
      <p>{user.email}</p>
      <p>{formatJoined(user.joinedAt)}</p>
    </article>
  );
}
