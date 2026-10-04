/** Canonical Coin shape — used across the portfolio page. */
export interface Coin {
  id: string;
  symbol: string;
  name: string;
  price: number;
  change_24h: number;
}
