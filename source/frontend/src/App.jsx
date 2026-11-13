import { useEffect, useRef, useState } from "react";
import { api, EXPLAIN_PROMPT, niceMonth } from "./api.js";
import { useChats } from "./useChats.js";
import Sidebar from "./components/Sidebar.jsx";
import Chat from "./components/Chat.jsx";
import Level1View from "./components/Level1View.jsx";

const uid = () => Math.random().toString(36).slice(2, 10);

export default function App() {
  const { chats, add, update, remove } = useChats();
  const [view, setView] = useState({ mode: "chat", id: null }); // chat -> Level 2, l1 -> Level 1 sample
  const [samples, setSamples] = useState([]);
  const [working, setWorking] = useState({}); // chatId -> "reading" | "thinking"
  const [navOpen, setNavOpen] = useState(false);
  const localImages = useRef({}); // chatId -> object URL shown while the upload is in flight

  useEffect(() => { api.listBills().then(setSamples).catch(() => setSamples([])); }, []);

  const active = view.mode === "chat" ? chats.find((c) => c.id === view.id) || null : null;
  const setBusy = (id, v) => setWorking((w) => ({ ...w, [id]: v }));
  const push = (id, msg) => update(id, (c) => ({ messages: [...c.messages, { id: uid(), ...msg }] }));
  const openChat = (id) => { setView({ mode: "chat", id }); setNavOpen(false); };

  async function uploadBill(file) {
    const id = uid();
    localImages.current[id] = URL.createObjectURL(file);
    add({ id, title: "New bill", billId: null, messages: [{ id: uid(), role: "user", type: "image" }] });
    openChat(id);
    setBusy(id, "reading");
    try {
      const { id: billId, data, issues } = await api.upload(file);
      const title = [data.provider, niceMonth(data.bill_month)].filter(Boolean).join(" · ") || "Electricity bill";
      update(id, (c) => ({
        billId,
        title,
        messages: [
          { ...c.messages[0], billId },
          { id: uid(), role: "assistant", type: "card", data, issues },
        ],
      }));
      setBusy(id, "thinking");
      try {
        const { answer } = await api.ask(billId, EXPLAIN_PROMPT, []);
        push(id, { role: "assistant", type: "text", text: answer, suggest: true });
      } catch {
        push(id, { role: "assistant", type: "text", text: "Your bill is read — ask me anything about it below.", suggest: true });
      }
    } catch (e) {
      push(id, { role: "assistant", type: "text", error: true, text: `I couldn't read that image. ${e.message}` });
    } finally {
      setBusy(id, "");
    }
  }

  async function sendQuestion(text) {
    const q = text.trim();
    if (!active || !active.billId || working[active.id] || !q) return;
    const id = active.id;
    const history = active.messages.filter((m) => m.type === "text").map((m) => ({ role: m.role, text: m.text }));
    push(id, { role: "user", type: "text", text: q });
    setBusy(id, "thinking");
    try {
      const { answer } = await api.ask(active.billId, q, history);
      push(id, { role: "assistant", type: "text", text: answer });
    } catch (e) {
      push(id, { role: "assistant", type: "text", error: true, text: `Sorry, I couldn't answer that. ${e.message}` });
    } finally {
      setBusy(id, "");
    }
  }

  return (
    <div className={`shell ${navOpen ? "nav-open" : ""}`}>
      <Sidebar
        chats={chats}
        samples={samples}
        view={view}
        onNew={() => openChat(null)}
        onSelectChat={openChat}
        onDeleteChat={(id) => { remove(id); if (view.mode === "chat" && id === view.id) openChat(null); }}
        onSelectSample={(id) => { setView({ mode: "l1", id }); setNavOpen(false); }}
      />
      <div className="scrim" onClick={() => setNavOpen(false)} />
      {view.mode === "l1" ? (
        <Level1View key={view.id} billId={view.id} />
      ) : (
        <Chat
          key={view.id || "new"}
          chat={active}
          status={active ? working[active.id] : ""}
          localImage={active ? localImages.current[active.id] : null}
          onMenu={() => setNavOpen(true)}
          onUpload={uploadBill}
          onSend={sendQuestion}
        />
      )}
    </div>
  );
}
