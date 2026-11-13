import { useEffect, useRef, useState } from "react";
import { api, SUGGESTIONS } from "../api.js";
import BillCard from "./BillCard.jsx";

const Avatar = () => <span className="avatar">⚡</span>;

function Message({ m, localImage, onSuggest, showSuggest }) {
  if (m.role === "user" && m.type === "image") {
    return (
      <div className="row user">
        <div className="bubble img">
          <img src={m.billId ? api.imageUrl(m.billId) : localImage} alt="Your bill" />
        </div>
      </div>
    );
  }
  if (m.role === "user") {
    return <div className="row user"><div className="bubble">{m.text}</div></div>;
  }
  return (
    <div className="row bot">
      <Avatar />
      <div className="body">
        {m.type === "card" ? <BillCard data={m.data} issues={m.issues} /> : <p className={m.error ? "err" : ""}>{m.text}</p>}
        {showSuggest && (
          <div className="chips">
            {SUGGESTIONS.map((s) => <button key={s} onClick={() => onSuggest(s)}>{s}</button>)}
          </div>
        )}
      </div>
    </div>
  );
}

export default function Chat({ chat, status, localImage, onMenu, onUpload, onSend }) {
  const [text, setText] = useState("");
  const [over, setOver] = useState(false);
  const file = useRef(null);
  const end = useRef(null);
  const canAsk = !!chat?.billId && !status;

  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [chat?.messages.length, status]);

  const pick = (f) => f && /^image\//.test(f.type) && onUpload(f);
  const submit = (e) => { e.preventDefault(); if (canAsk && text.trim()) { onSend(text); setText(""); } };
  const lastSuggest = chat ? [...chat.messages].reverse().find((m) => m.suggest)?.id : null;
  const asked = chat?.messages.some((m) => m.role === "user" && m.type === "text");

  return (
    <section
      className={`chat ${over ? "over" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files[0]); }}
      onPaste={(e) => pick([...e.clipboardData.files][0])}
    >
      <header className="bar-top">
        <button className="menu" onClick={onMenu} aria-label="Open menu">☰</button>
        <span>{chat ? chat.title : "Bill Decoder"}</span>
      </header>

      <div className="scroll">
        {!chat ? (
          <div className="hero">
            <span className="logo big">⚡</span>
            <h1>Upload your electricity bill</h1>
            <p>Get a plain-language breakdown of your K-Electric, LESCO or IESCO bill — then ask anything about it.</p>
            <button className="drop" onClick={() => file.current.click()}>
              <span className="drop-icon">↑</span>
              <b>Choose a photo or screenshot</b>
              <small>or drag &amp; drop, or paste an image</small>
            </button>
            <small className="privacy">Names and ID numbers are never returned.</small>
          </div>
        ) : (
          <div className="thread">
            {chat.messages.map((m) => (
              <Message key={m.id} m={m} localImage={localImage}
                showSuggest={m.id === lastSuggest && !asked && !status}
                onSuggest={onSend} />
            ))}
            {status && (
              <div className="row bot">
                <Avatar />
                <div className="body">
                  <p className="dim typing">
                    {status === "reading" ? "Reading your bill" : "Thinking"}<span className="dots"><i /><i /><i /></span>
                  </p>
                </div>
              </div>
            )}
            <div ref={end} />
          </div>
        )}
      </div>

      <form className="composer" onSubmit={submit}>
        <input ref={file} type="file" accept="image/png,image/jpeg" hidden
          onChange={(e) => { pick(e.target.files[0]); e.target.value = ""; }} />
        <button type="button" className="attach" title="Upload a bill" onClick={() => file.current.click()}>＋</button>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={!chat?.billId}
          placeholder={chat?.billId ? "Ask about your bill…" : "Upload a bill to start asking questions"}
        />
        <button className="send" disabled={!canAsk || !text.trim()} aria-label="Send">↑</button>
      </form>
    </section>
  );
}
