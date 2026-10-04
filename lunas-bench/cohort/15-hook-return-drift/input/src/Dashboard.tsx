import { useCoins } from './hooks/useCoins';

function formatDate(d: Date): string {
  return d.toLocaleString();
}

export function Dashboard() {
  // BUG: destructures `lastUpdated` — but useCoins only returns
  // { coins, isLoading }. `lastUpdated` is undefined; `formatDate`
  // crashes when called with undefined.
  const { coins, isLoading, lastUpdated } = useCoins();

  if (isLoading) return <p>Loading…</p>;

  return (
    <section>
      <p>Last updated: {formatDate(lastUpdated)}</p>
      <ul>
        {coins.map((c) => (
          <li key={c.symbol}>{c.symbol} — ${c.price.toFixed(2)}</li>
        ))}
      </ul>
    </section>
  );
}
