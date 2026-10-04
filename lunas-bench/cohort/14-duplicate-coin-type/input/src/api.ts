import type { Coin } from './types';

/** Returns a fixed sample portfolio. Real implementation would fetch
 *  from a price API; this is a fixture for the case. */
export function loadPortfolio(): Coin[] {
  return [
    { id: 'btc', symbol: 'BTC', name: 'Bitcoin',  price: 67_432.10, change_24h:  2.31 },
    { id: 'eth', symbol: 'ETH', name: 'Ethereum', price:  3_512.45, change_24h: -0.84 },
    { id: 'sol', symbol: 'SOL', name: 'Solana',   price:    142.88, change_24h:  4.17 },
  ];
}
