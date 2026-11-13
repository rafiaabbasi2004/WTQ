import { LABELS, money, niceDate, niceMonth } from "../api.js";

function Lines({ title, items, total }) {
  if (!items.length && total == null) return null;
  return (
    <details>
      <summary>
        {title} <span className="count">{items.length ? `${items.length} items` : "combined"}</span>
        <b>{money(total ?? items.reduce((s, i) => s + i.amount, 0))}</b>
      </summary>
      {items.length === 0 ? (
        <p className="dim">Only a combined amount is printed on this bill.</p>
      ) : (
        <ul>
          {items.map((i, k) => (
            <li key={k}>
              <span>{LABELS[i.type] || i.type}</span>
              <span className={i.amount < 0 ? "neg" : ""}>{money(i.amount)}</span>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

export default function BillCard({ data, issues }) {
  const costPerUnit = data.units_consumed && data.current_bill ? data.current_bill / data.units_consumed : null;
  const charges = data.total_charges ?? data.charges.reduce((s, c) => s + c.amount, 0);
  const taxes = data.total_taxes ?? data.taxes.reduce((s, t) => s + t.amount, 0);
  const total = charges + taxes;
  const taxPct = total > 0 ? (taxes / total) * 100 : null;

  const stats = [
    ["Units used", data.units_consumed != null ? `${data.units_consumed} kWh` : null],
    ["Cost per unit", costPerUnit != null ? money(costPerUnit) : null],
    ["This month's bill", money(data.current_bill)],
    ["Arrears", data.arrears != null ? money(data.arrears) : null],
    ["Meter reading", data.previous_reading != null && data.current_reading != null ? `${data.previous_reading} → ${data.current_reading}` : null],
    ["Issued", niceDate(data.issue_date)],
  ].filter(([, v]) => v);

  return (
    <div className="bill">
      <div className="bill-head">
        <span className="badge">{data.provider || "Bill"}</span>
        <span>{niceMonth(data.bill_month) || "Electricity bill"}</span>
        {data.tariff && <span className="dim">· Tariff {data.tariff}</span>}
        {data.sanctioned_load_kw != null && <span className="dim">· {data.sanctioned_load_kw} kW load</span>}
      </div>

      <div className="pay">
        <div>
          <small>Pay by {niceDate(data.due_date) || "the due date"}</small>
          <div className="amount">{money(data.payable_within_due_date)}</div>
        </div>
        <div className="late">
          <small>After due date</small>
          <div>{money(data.payable_after_due_date)}</div>
        </div>
      </div>

      <div className="stats">
        {stats.map(([k, v]) => (
          <div key={k}><small>{k}</small><b>{v}</b></div>
        ))}
      </div>

      {taxPct != null && (
        <div className="split">
          <div className="bar">
            <span style={{ width: `${100 - taxPct}%` }} className="seg-a" />
            <span style={{ width: `${taxPct}%` }} className="seg-b" />
          </div>
          <div className="bar-legend">
            <span><i className="seg-a" />Charges {money(charges)}</span>
            <span><i className="seg-b" />Taxes {money(taxes)} ({taxPct.toFixed(1)}%)</span>
          </div>
        </div>
      )}

      <Lines title="Charges" items={data.charges} total={data.total_charges} />
      <Lines title="Taxes & duties" items={data.taxes} total={data.total_taxes} />

      {issues?.length > 0 && (
        <p className="note">Some printed totals on this bill don't add up exactly — worth double-checking the original.</p>
      )}
    </div>
  );
}
