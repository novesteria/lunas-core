// Tip Calculator — wiring layer.
//
// The HTML provides inputs, buttons, and output slots. This script
// reads the inputs, computes the tip, and writes the outputs.

const TIP_RATE = 0.15;

function readInputs() {
  const bill = parseFloat(document.getElementById('bill').value || '0');
  const people = parseInt(document.getElementById('people-count').textContent || '1', 10);
  return { bill, people: Math.max(1, people) };
}

function render(tip, total) {
  document.getElementById('tip-per-person').textContent = `$${tip.toFixed(2)}`;
  document.getElementById('total-per-person').textContent = `$${total.toFixed(2)}`;
}

function calculate() {
  const { bill, people } = readInputs();
  const tipTotal = bill * TIP_RATE;
  const tip = tipTotal / people;
  const total = (bill + tipTotal) / people;
  render(tip, total);
}

// BUG: HTML declares id="theme-switch" but this script hooks #theme-toggle.
// HTML declares id="people-decrement" but this script hooks #decrement-btn.
// Both pairs are realistic id-mismatch patterns: the script author
// and the HTML author settled on different naming conventions and
// never reconciled.
document.getElementById('calculate-btn').addEventListener('click', calculate);
document.getElementById('theme-toggle').addEventListener('click', () => {
  document.body.dataset.theme =
    document.body.dataset.theme === 'dark' ? 'light' : 'dark';
});
document.getElementById('decrement-btn').addEventListener('click', () => {
  const out = document.getElementById('people-count');
  out.textContent = String(Math.max(1, parseInt(out.textContent, 10) - 1));
});
document.getElementById('people-increment').addEventListener('click', () => {
  const out = document.getElementById('people-count');
  out.textContent = String(parseInt(out.textContent, 10) + 1);
});
