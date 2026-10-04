// BUG: this file redeclares `Coin` locally with a DIFFERENT shape
// than src/types.ts. The local Coin only has { name, value } — no
// symbol, no price, no change_24h. Because the component uses this
// local Coin, calling code that passes a real Coin from the API loses
// the symbol, price, and change_24h fields silently — they're not
// even read here. The UI renders blanks for what should be numeric
// values. tsc TS2300 only fires if BOTH declarations are in the same
// scope; here they're in different files, so the bug ships green.

interface Coin {
  name: string;
  value: number;
}

export interface CoinRowProps {
  coin: Coin;
}

export function CoinRow({ coin }: CoinRowProps) {
  return (
    <tr>
      <td>{coin.name}</td>
      <td>{coin.value}</td>
    </tr>
  );
}
