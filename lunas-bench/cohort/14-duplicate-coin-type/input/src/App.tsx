import { loadPortfolio } from './api';
import { CoinRow } from './components/CoinRow';

export default function App() {
  const coins = loadPortfolio();
  return (
    <main>
      <h1>Portfolio</h1>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Value</th>
          </tr>
        </thead>
        <tbody>
          {/* Each row receives a Coin from the API. But CoinRow's local
              type only knows { name, value } — symbol, price, change_24h
              never reach the UI. */}
          {coins.map((c) => (
            <CoinRow key={c.id} coin={c as any} />
          ))}
        </tbody>
      </table>
    </main>
  );
}
