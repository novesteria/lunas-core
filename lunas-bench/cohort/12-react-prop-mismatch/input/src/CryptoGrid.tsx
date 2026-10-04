import { CryptoCard } from './CryptoCard';
import type { CryptoCurrency } from './types';

const SAMPLE: CryptoCurrency[] = [
  { symbol: 'BTC', name: 'Bitcoin', price: 67_432.10 },
  { symbol: 'ETH', name: 'Ethereum', price: 3_512.45 },
  { symbol: 'SOL', name: 'Solana', price: 142.88 },
];

export function CryptoGrid() {
  return (
    <section className="grid">
      {SAMPLE.map((c) => (
        // BUG: CryptoCard declares `coin: CryptoCurrency` in its Props,
        // but here we pass `crypto={c}` instead of `coin={c}`. The
        // CryptoCard renders with `coin` undefined → crashes on
        // `coin.price.toFixed`.
        <CryptoCard key={c.symbol} crypto={c} />
      ))}
    </section>
  );
}
