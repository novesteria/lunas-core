"""Print a compact one-row-per-case summary from a bench results JSON."""

import json
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else 'results-nollm.json')
data = json.loads(path.read_text(encoding='utf-8'))

for r in data['rows']:
    name = r['case']
    status = r['status'].upper()
    detail = ''
    if r['status'] == 'fail':
        problems = r.get('problems') or []
        if problems:
            detail = problems[0]
    elif r['status'] == 'error':
        detail = r.get('reason') or ''
    elif r['status'] == 'skip':
        detail = r.get('reason') or ''
    print(f'{name:<42} {status:<6} {detail}')

print()
print(f'Total: {data["total"]}  counts={data["counts"]}  use_llm={data["use_llm"]}')
