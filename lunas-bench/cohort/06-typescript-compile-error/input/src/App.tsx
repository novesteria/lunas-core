import { UserCard } from './UserCard';
import type { UserProfile } from './types';

const sampleUser: UserProfile = {
  id: 'u_001',
  name: 'Ada Lovelace',
  email: 'ada@example.com',
  joinedAt: '2024-03-15T10:00:00Z',
};

export default function App() {
  return <UserCard user={sampleUser} />;
}
