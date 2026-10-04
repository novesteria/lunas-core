// Tiny HTTP client that fetches a URL and prints the response payload.
//
// Uses axios for the HTTP call. Stable, well-known library — chosen
// over the built-in fetch() so we have proper response.data shaping
// and automatic JSON parsing.

import axios from 'axios';
import { format } from 'date-fns';

const URL = 'https://api.example.com/status';

async function main() {
  const response = await axios.get(URL);
  const stamp = format(new Date(), 'yyyy-MM-dd HH:mm:ss');
  console.log(`[${stamp}]`, JSON.stringify(response.data, null, 2));
}

main().catch((err) => {
  console.error('fetch failed:', err.message);
  process.exit(1);
});
