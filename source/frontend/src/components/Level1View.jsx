import { useEffect, useState } from "react";
import { api, LABELS, money } from "../api.js";

const STEPS = [
  ["1", "Bill image", "Photo or screenshot, auto-rotated and resized"],
  ["2", "Vision model reads it", "Gemini returns every field in a strict schema"],
  ["3", "Rules & checks", "Types normalised, totals cross-checked, re-read if inconsistent"],
  ["4", "Level 1 JSON", "One validated object per bill"],
];

const show = (v) => (v === null || v === undefined ? <span className="nullv">null</span> : String(v));

function Group({ title, rows }) {
  return (
    <section className="card">
      <h3>{title}</h3>
      <dl className="kv">
        {rows.map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd>{show(v)}</dd></div>
        ))}
      </dl>
    </section>
  );
}

function Lines({ title, items, total, totalKey }) {
  return (
    <section className="card">
      <h3>{title}</h3>
      {items.length === 0 ? (
        <p className="dim">[] — {total != null ? "only a combined amount is printed" : "no lines"}</p>
      ) : (
        <table className="lines">
          <tbody>
            {items.map((c, i) => (
              <tr key={i}>
                <td><span className="pill">{c.type}</span> <span className="dim">{LABELS[c.type]}</span></td>
                <td className={c.amount < 0 ? "neg" : ""}>{c.amount}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="sub"><span>{totalKey}</span><b>{show(total)}</b></div>
    </section>
  );
}

export default function Level1View({ billId }) {
  const [state, setState] = useState({ loading: true });

  const load = async (refresh = false) => {
    setState({ loading: true });
    try {
      setState({ ...(await api.getBill(billId, refresh)), loading: false });
    } catch (e) {
      setState({ loading: false, error: e.message });
    }
  };
  useEffect(() => { load(); }, [billId]); // eslint-disable-line react-hooks/exhaustive-deps

  const { loading, error, data: d, issues } = state;
  const json = d ? JSON.stringify(d, null, 2) : "";

  return (
    <section className="chat">
      <div className="scroll">
        <div className="l1">
          <header className="l1-head">
            <div>
              <span className="level-tag">Level 1</span>
              <h1>{billId.replace("_", " ")}</h1>
            </div>
            <button className="ghost" disabled={loading} onClick={() => load(true)}>
              {loading ? "Reading…" : "Re-read this bill"}
            </button>
          </header>

          <ol className="steps">
            {STEPS.map(([n, t, s]) => (
              <li key={n}><span className="n">{n}</span><div><b>{t}</b><small>{s}</small></div></li>
            ))}
          </ol>

          <div className="l1-grid">
            <section className="card img-card">
              <h3>Input · original bill</h3>
              <div className="img-wrap"><img src={api.imageUrl(billId)} alt={billId} /></div>
            </section>

            <div className="l1-right">
              {loading && <section className="card"><p className="dim typing">Reading the bill<span className="dots"><i /><i /><i /></span></p></section>}
              {error && <section className="card"><p className="err">Could not read this bill. {error}</p></section>}
              {d && (
                <>
                  <section className={`status ${issues.length ? "warn" : "ok"}`}>
                    {issues.length === 0
                      ? "✓ All consistency checks passed (readings, charges and taxes add up to the printed totals)"
                      : <>Checks flagged for review:<ul>{issues.map((i) => <li key={i}>{i}</li>)}</ul></>}
                  </section>
                  <Group title="Bill" rows={[["provider", d.provider], ["tariff", d.tariff], ["sanctioned_load_kw", d.sanctioned_load_kw], ["bill_month", d.bill_month]]} />
                  <Group title="Dates" rows={[["reading_date", d.reading_date], ["issue_date", d.issue_date], ["due_date", d.due_date]]} />
                  <Group title="Meter" rows={[["previous_reading", d.previous_reading], ["current_reading", d.current_reading], ["units_consumed", d.units_consumed]]} />
                  <Lines title="Charges" items={d.charges} total={d.total_charges} totalKey="total_charges" />
                  <Lines title="Taxes" items={d.taxes} total={d.total_taxes} totalKey="total_taxes" />
                  <Group title="Amounts" rows={[["current_bill", d.current_bill != null ? money(d.current_bill) : null], ["arrears", d.arrears != null ? money(d.arrears) : null],
                    ["payable_within_due_date", d.payable_within_due_date != null ? money(d.payable_within_due_date) : null],
                    ["payable_after_due_date", d.payable_after_due_date != null ? money(d.payable_after_due_date) : null]]} />
                </>
              )}
            </div>

          </div>

          {d && (
            <div className="l1-json">
              <section className="card json-card">
                <h3>
                  Output · Level 1 JSON
                  <button className="ghost sm" onClick={() => navigator.clipboard.writeText(json)}>Copy</button>
                </h3>
                <pre>{json}</pre>
              </section>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
