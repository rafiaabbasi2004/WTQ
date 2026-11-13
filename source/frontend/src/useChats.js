import { useCallback, useEffect, useState } from "react";

const KEY = "bill-decoder.chats.v1";

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || [];
  } catch {
    return [];
  }
}

/** Conversations live in the browser; bills and their data live on the server (keyed by billId). */
export function useChats() {
  const [chats, setChats] = useState(load);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(chats));
    } catch {
      /* storage full or blocked: keep working in memory */
    }
  }, [chats]);

  const add = useCallback((chat) => setChats((c) => [chat, ...c]), []);
  const update = useCallback(
    (id, fn) => setChats((c) => c.map((x) => (x.id === id ? { ...x, ...fn(x) } : x))),
    [],
  );
  const remove = useCallback((id) => setChats((c) => c.filter((x) => x.id !== id)), []);

  return { chats, add, update, remove };
}
