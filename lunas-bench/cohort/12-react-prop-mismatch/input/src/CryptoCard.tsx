import type { CryptoCurrency } from './types';

export interface CryptoCardProps {
  coin: CryptoCurrency;
}

export function CryptoCard({ coin }: CryptoCardProps) {
  return (
    <article className="crypto-card">
      <header>
        <span className="symbol">{coin.symbol}</span>
        <span className="name">{coin.name}</span>
      </header>
      <p className="price">${coin.price.toFixed(2)}</p>
    </article>
  );
}
