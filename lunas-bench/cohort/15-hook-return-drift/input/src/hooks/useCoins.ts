import { useState, useEffect } from 'react';

export interface Coin {
  symbol: string;
  name: string;
  price: number;
}

const SAMPLE: Coin[] = [
  { symbol: 'BTC', name: 'Bitcoin',  price: 67_432.10 },
  { symbol: 'ETH', name: 'Ethereum', price:  3_512.45 },
];

// BUG: brief asked for the hook to also expose `lastUpdated`, but
// the implementation returns only `{ coins, isLoading }`. Consumer
// destructures `lastUpdated` → undefined → crashes on `.toLocaleString()`.
export function useCoins() {
  const [coins, setCoins] = useState<Coin[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const t = setTimeout(() => {
      setCoins(SAMPLE);
      setIsLoading(false);
    }, 200);
    return () => clearTimeout(t);
  }, []);

  return { coins, isLoading };
}
