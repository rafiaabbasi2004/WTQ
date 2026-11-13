async function request(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try {
      msg = (await r.json()).detail || msg;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(msg);
  }
  return r.json();
}

const enc = encodeURIComponent;

export const api = {
  listBills: () => request("/api/bills"),
  getBill: (id, refresh = false) => request(`/api/bills/${enc(id)}${refresh ? "?refresh=true" : ""}`),
  imageUrl: (id) => `/api/bills/${enc(id)}/image`,
  upload: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return request("/api/upload", { method: "POST", body: fd });
  },
  ask: (id, question, history) =>
    request(`/api/bills/${enc(id)}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history }),
    }),
};

export const money = (n) =>
  n === null || n === undefined ? "—" : "Rs. " + Number(n).toLocaleString("en-PK", { maximumFractionDigits: 2 });

export const LABELS = {
  energy: "Energy", fixed: "Fixed charges", fpa: "Fuel price adjustment", quarterly_adjustment: "Quarterly adjustment",
  surcharge: "Surcharge", meter_rent: "Meter rent", subsidy: "Subsidy", other: "Other",
  gst: "Sales tax (GST)", electricity_duty: "Electricity duty", income_tax: "Income tax",
  municipal_tax: "Municipal tax", other_tax: "Other tax",
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function niceDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}` : null;
}
export function niceMonth(ym) {
  const m = /^(\d{4})-(\d{2})/.exec(ym || "");
  return m ? `${MONTHS[Number(m[2]) - 1]} ${m[1]}` : null;
}

export const EXPLAIN_PROMPT =
  "Explain this bill to me in simple words: what I owe and by when, what makes up the cost, how my usage looks, " +
  "and anything I should watch out for. Keep it short.";

export const SUGGESTIONS = [
  "How much of my bill is taxes?",
  "What happens if I pay after the due date?",
  "How does my usage compare to previous months?",
  "What is my average cost per unit?",
];
