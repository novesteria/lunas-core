// Notes — composer + list renderer.
//
// The header has the app title; no theme button was added. The brief
// asked for a switcher in the header — the implementation never
// landed.

const STATE = { notes: [] };

function render() {
  const list = document.getElementById('notes-list');
  list.innerHTML = STATE.notes
    .map((n) => `<li>${escapeHtml(n.text)}</li>`)
    .join('');
}

function escapeHtml(s) {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function add() {
  const ta = document.getElementById('input');
  const text = ta.value.trim();
  if (!text) return;
  STATE.notes.unshift({ id: Date.now(), text });
  ta.value = '';
  render();
}

document.getElementById('add-btn').addEventListener('click', add);
document.getElementById('input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
    e.preventDefault();
    add();
  }
});

render();
