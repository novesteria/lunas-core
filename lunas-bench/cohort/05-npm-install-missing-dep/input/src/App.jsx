import { useState } from "react";

export default function App() {
  const [todos, setTodos] = useState([]);
  const [input, setInput] = useState("");

  const addTodo = (e) => {
    e.preventDefault();
    if (!input.trim()) return;
    setTodos([...todos, { id: Date.now(), text: input, done: false }]);
    setInput("");
  };

  const toggle = (id) =>
    setTodos(todos.map((t) => (t.id === id ? { ...t, done: !t.done } : t)));

  const remove = (id) => setTodos(todos.filter((t) => t.id !== id));

  const remaining = todos.filter((t) => !t.done).length;

  return (
    <main style={{ maxWidth: 480, margin: "2rem auto", padding: "1rem", fontFamily: "Inter, system-ui, sans-serif" }}>
      <h1 style={{ fontSize: "1.75rem", marginBottom: "1rem" }}>Todos</h1>
      <form onSubmit={addTodo} style={{ display: "flex", gap: "0.5rem", marginBottom: "1.5rem" }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="What needs doing?"
          style={{ flex: 1, padding: "0.5rem", border: "1px solid #C8CFC6", borderRadius: 2 }}
        />
        <button type="submit" style={{ padding: "0.5rem 1rem", background: "#476B57", color: "#E9ECE6", border: 0, borderRadius: 2 }}>
          Add
        </button>
      </form>
      <ul style={{ listStyle: "none", padding: 0 }}>
        {todos.map((t) => (
          <li key={t.id} style={{ display: "flex", alignItems: "center", gap: "0.5rem", padding: "0.5rem 0", borderBottom: "1px solid #C8CFC6" }}>
            <input type="checkbox" checked={t.done} onChange={() => toggle(t.id)} />
            <span style={{ flex: 1, textDecoration: t.done ? "line-through" : "none", color: t.done ? "#5E6863" : "#1F2421" }}>
              {t.text}
            </span>
            <button onClick={() => remove(t.id)} style={{ background: "transparent", border: 0, color: "#5E6863", cursor: "pointer" }}>
              ×
            </button>
          </li>
        ))}
      </ul>
      <p style={{ marginTop: "1.5rem", color: "#5E6863", fontSize: "0.9rem" }}>
        {remaining} remaining
      </p>
    </main>
  );
}
