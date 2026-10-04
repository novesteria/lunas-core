// User Dashboard — table + sortable columns.

const USERS = [
  { name: 'Ada Lovelace',   email: 'ada@example.com',   signup: '2024-01-15' },
  { name: 'Grace Hopper',   email: 'grace@example.com', signup: '2024-02-08' },
  { name: 'Linus Torvalds', email: 'linus@example.com', signup: '2024-03-22' },
  { name: 'Margaret Hamilton', email: 'mh@example.com', signup: '2024-04-11' },
];

let sortKey = 'name';
let sortDir = 'asc';

function render() {
  const tbody = document.getElementById('user-tbody');
  const sorted = [...USERS].sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    return (av < bv ? -1 : av > bv ? 1 : 0) * (sortDir === 'asc' ? 1 : -1);
  });
  tbody.innerHTML = sorted.map((u) =>
    `<tr><td>${u.name}</td><td>${u.email}</td><td>${u.signup}</td></tr>`
  ).join('');
}

document.querySelectorAll('th[data-sort]').forEach((th) => {
  th.addEventListener('click', () => {
    const key = th.dataset.sort;
    if (key === sortKey) {
      sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      sortKey = key;
      sortDir = 'asc';
    }
    render();
  });
});

render();
