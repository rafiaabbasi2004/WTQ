import { useState } from "react";

export default function Sidebar({ chats, samples, view, onNew, onSelectChat, onDeleteChat, onSelectSample }) {
  const [l1Open, setL1Open] = useState(true);
  const groups = [
    ["Training samples", samples.filter((b) => b.source === "train")],
    ["Test bills", samples.filter((b) => b.source === "test")],
  ].filter(([, items]) => items.length);

  return (
    <aside className="side">
      <div className="brand">
        <span className="logo">⚡</span>
        <b>Bill Decoder</b>
      </div>

      {/* ---------- Level 2: ask questions about a bill ---------- */}
      <div className="level">
        <span className="level-tag">Level 2</span>
        <span>Ask about your bill</span>
      </div>
      <button className="new" onClick={onNew}>
        <span className="plus">＋</span> New bill
      </button>
      <nav className="list chats">
        {chats.length === 0 && <p className="side-empty">Bills you upload will appear here.</p>}
        {chats.map((c) => (
          <div key={c.id} className={`item ${view.mode === "chat" && c.id === view.id ? "active" : ""}`}
            onClick={() => onSelectChat(c.id)}>
            <span className="item-title">{c.title}</span>
            <button className="del" title="Delete" onClick={(e) => { e.stopPropagation(); onDeleteChat(c.id); }}>✕</button>
          </div>
        ))}
      </nav>

      {/* ---------- Level 1: how a bill is read ---------- */}
      <button className={`level drop-head ${l1Open ? "open" : ""}`} onClick={() => setL1Open((o) => !o)}>
        <span className="level-tag">Level 1</span>
        <span>How bills are read</span>
        <span className="chev">›</span>
      </button>
      {l1Open && (
        <nav className="list l1">
          {groups.length === 0 && <p className="side-empty">No sample bills found.</p>}
          {groups.map(([title, items]) => (
            <div key={title}>
              <div className="side-title">{title}</div>
              {items.map((b) => (
                <div key={b.id} className={`item ${view.mode === "l1" && b.id === view.id ? "active" : ""}`}
                  onClick={() => onSelectSample(b.id)}>
                  <span className="item-title">{b.id}</span>
                  <span className="tag">{b.provider}</span>
                </div>
              ))}
            </div>
          ))}
        </nav>
      )}

      <div className="side-foot">Answers use only what is printed on your bill.</div>
    </aside>
  );
}
