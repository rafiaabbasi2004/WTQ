"""Level 2: answer customer questions about a bill.

The model sees the bill image plus the Level 1 JSON, extra context read from the bill
(usage / payment history, notes, majority-voted over several reads) and metrics computed in
code (averages, seasonal totals, trends, forecasts, payment status), so numbers are not left
to the model's mental arithmetic.
"""
import io
import json
import logging
import re
from pathlib import Path
from typing import Optional

from google.genai import types
from PIL import Image, ImageOps
from pydantic import BaseModel

from .extract import BillExtractor, load_image_bytes
from .llm import retry_call

log = logging.getLogger("bill_decoder")


# ---------- extra context printed on the bill (history tables, message board) ----------
class UsageMonth(BaseModel):
    month: str                      # YYYY-MM when determinable, else as printed
    units: Optional[float] = None


class PaymentRecord(BaseModel):
    month: str
    billed: Optional[float] = None
    paid: Optional[float] = None
    pay_date: Optional[str] = None  # YYYY-MM-DD when determinable


class Extras(BaseModel):
    usage_history: list[UsageMonth] = []
    payment_history: list[PaymentRecord] = []
    notes: list[str] = []


def band_images(path: Path) -> list[bytes]:
    """Three overlapping, upscaled bands of the page. Small table text is far easier to read when zoomed."""
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    w, h = img.size
    out = []
    for top, bottom in ((0.0, 0.40), (0.30, 0.70), (0.55, 1.0)):
        c = img.crop((0, int(h * top), w, int(h * bottom)))
        scale = min(3.0, max(1.0, 2600 / max(c.size)))
        c = c.resize((round(c.width * scale), round(c.height * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        c.save(buf, format="PNG")
        out.append(buf.getvalue())
    return out


EXTRAS_PROMPT = """Read this Pakistani electricity bill image and extract ONLY the following, as printed:
1. usage_history: the monthly consumption history (e.g. a "13 month usage history" bar chart or table of units per
   month). One entry per month, oldest first. The last bar is normally the current billing month. Give month as
   YYYY-MM using the bill's own month as the anchor; units as a number.
2. payment_history: the billing & payment history table (month, billed amount, amount paid, payment date), if present.
3. notes: any message-board / notice text on the bill, translated to English, one short string per message.
Table reading rules: history tables are often split into two side-by-side column groups (e.g. left group Aug-Jan,
right group Feb-Jul). Read the left group top to bottom, then the right group top to bottom. Every row has its OWN
month label; take the month from the label printed on that row, never from its position. Include every row,
including partly overlapped ones. A "0" or blank payment means nothing was paid that month. The bill month itself
is normally not part of the history table (it is the current bill).
For history tables with the columns MONTH, UNITS, BILL, PAYMENT, read each row as ONE unit: usage_history takes
(month, units) and payment_history takes (month, bill, payment) from the SAME row, so both lists cover the same
months. Table-header text (such as "UNITS" or "BILL (RS.)") sometimes overlaps the first row of a column group; the
number printed there still belongs to that first row, so do not skip it or let the rows below slide up into it.
Before answering, count the rows in each column group and make sure you returned that many entries.
You receive the full bill followed by three zoomed, overlapping crops (top, middle, bottom of the page). Use the zoomed crops
to read small table text; each table appears once on the bill, so do not duplicate rows that are visible in more
than one crop.
If a section is not on the bill return an empty list. Never include names, addresses or ID/account/meter numbers.
Return only the JSON object."""


# ---------- metrics computed in code ----------
def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return round(a / b * 100, 2) if a is not None and b else None


_YM = re.compile(r"^(\d{4})-(\d{2})")


def _ym(s: Optional[str]) -> Optional[tuple[int, int]]:
    m = _YM.match(s or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _avg(vals: list[float]) -> Optional[float]:
    return round(sum(vals) / len(vals), 1) if vals else None


def history_analysis(bill: dict, extras: Extras, units: Optional[float]) -> dict:
    """Seasonal / trend / forecast / payment facts computed in code from the history tables."""
    out: dict = {}
    cur = _ym(bill.get("bill_month"))
    by_month: dict[tuple[int, int], float] = {}
    for u in extras.usage_history:
        k = _ym(u.month)
        if k and u.units is not None:
            by_month[k] = u.units
    if cur and units is not None:
        by_month.setdefault(cur, units)  # the current month is also part of the picture
    if by_month and cur:
        ordered = sorted(by_month.items())
        prev = [(k, v) for k, v in ordered if k < cur]
        fmt = lambda k: f"{k[0]}-{k[1]:02d}"
        out["usage_months_available"] = {fmt(k): v for k, v in ordered}

        last12 = prev[-12:]
        if last12:
            hi = max(last12, key=lambda kv: kv[1])
            out["highest_month_in_previous_12"] = {"month": fmt(hi[0]), "units": hi[1]}
            out["average_units_previous_12_months"] = _avg([v for _, v in last12])
            out["previous_months_used_for_average"] = len(last12)
        same = (cur[0] - 1, cur[1])
        if same in by_month:
            out["same_month_last_year_units"] = by_month[same]
            if units is not None:
                out["this_month_minus_same_month_last_year"] = round(units - by_month[same], 1)

        summer = {k: v for k, v in by_month.items() if k[1] in (6, 7, 8)}
        winter = {k: v for k, v in by_month.items() if k[1] in (12, 1, 2)}
        if summer and winter:
            out["summer_months_June_to_Aug"] = {fmt(k): v for k, v in sorted(summer.items())}
            out["winter_months_Dec_to_Feb"] = {fmt(k): v for k, v in sorted(winter.items())}
            out["summer_average_units"] = _avg(list(summer.values()))
            out["winter_average_units"] = _avg(list(winter.values()))
            out["summer_minus_winter_average_units"] = round(_avg(list(summer.values())) - _avg(list(winter.values())), 1)
            dup = sorted({k[1] for k in summer} & {k[1] for k in winter}) or []
            repeated = sorted(m for m in {k[1] for k in by_month} if sum(1 for k in by_month if k[1] == m) > 1)
            if repeated:
                out["seasonal_note"] = (f"calendar month(s) {repeated} appear twice in the history window (different "
                                        f"years); averages treat each listed month once, so state which months you used")
            if repeated:  # one value per calendar month: keep the most recent occurrence
                def latest(d):
                    keep = {}
                    for k in sorted(d):
                        keep[k[1]] = (k, d[k])
                    return {fmt(k): v for k, v in keep.values()}
                sl, wl = latest(summer), latest(winter)
                out["summer_months_latest_year_per_month"] = sl
                out["winter_months_latest_year_per_month"] = wl
                out["summer_total_latest_year_per_month"] = round(sum(sl.values()), 1)
                out["winter_total_latest_year_per_month"] = round(sum(wl.values()), 1)
                out["summer_average_latest_year_per_month"] = _avg(list(sl.values()))
                out["winter_average_latest_year_per_month"] = _avg(list(wl.values()))
                out["summer_minus_winter_average_latest_year_per_month"] = round(
                    _avg(list(sl.values())) - _avg(list(wl.values())), 1)
            out["summer_total_units"] = round(sum(summer.values()), 1)
            out["winter_total_units"] = round(sum(winter.values()), 1)

        recent = ordered[-3:]
        if len(recent) == 3:
            out["last_3_months_units"] = {fmt(k): v for k, v in recent}
            d = recent[-1][1] - recent[0][1]
            out["last_3_months_change_first_to_last"] = round(d, 1)
        if prev:
            out["previous_month_units"] = prev[-1][1]
            if bill.get("current_bill") and units:
                out["estimated_bill_if_units_equal_previous_month_at_current_cost_per_unit"] = round(
                    prev[-1][1] * bill["current_bill"] / units, 2)
        # forecast candidates for next month (all estimates)
        fc = {}
        if last12:
            fc["average_of_previous_12"] = _avg([v for _, v in last12])
        n_next = (cur[0] + (cur[1] // 12), cur[1] % 12 + 1)
        ly = (n_next[0] - 1, n_next[1])
        if ly in by_month:
            fc["same_month_last_year"] = by_month[ly]
        pts = [v for _, v in ordered][-12:]
        if len(pts) >= 4:
            n = len(pts)
            xm, ym_ = (n - 1) / 2, sum(pts) / n
            den = sum((i - xm) ** 2 for i in range(n))
            slope = sum((i - xm) * (p - ym_) for i, p in enumerate(pts)) / den
            fc["linear_trend_next_month"] = round(ym_ + slope * (n - xm), 1)
        if fc:
            out["next_month_forecast_candidates_units"] = {"month": fmt(n_next), **fc}

    pays = [p for p in extras.payment_history if p.billed is not None]
    if pays:
        unpaid = [p.month for p in pays if not p.paid]
        short = [p.month for p in pays if p.paid and p.billed and p.paid + 1 < p.billed]
        out["payment_history_rows"] = len(pays)
        out["months_with_no_payment_recorded"] = unpaid
        out["months_paid_less_than_billed"] = short
        out["average_billed_amount"] = round(sum(p.billed for p in pays) / len(pays), 2)
        out["total_billed_in_payment_history"] = round(sum(p.billed for p in pays), 2)
    return out


def compute_metrics(bill: dict, extras: Extras) -> dict:
    charges_sum = round(sum(c["amount"] for c in bill.get("charges", [])), 2)
    taxes_sum = round(sum(t["amount"] for t in bill.get("taxes", [])), 2)
    total_taxes = bill.get("total_taxes") if bill.get("total_taxes") is not None else (taxes_sum or None)
    cur, units = bill.get("current_bill"), bill.get("units_consumed")
    within, after = bill.get("payable_within_due_date"), bill.get("payable_after_due_date")
    m: dict = {
        "taxes_total": total_taxes,
        "taxes_percent_of_current_bill": _pct(total_taxes, cur),
        "charges_total": bill.get("total_charges") if bill.get("total_charges") is not None else (charges_sum or None),
        "cost_per_unit_current_bill_over_units": round(cur / units, 2) if cur and units else None,
        "late_payment_extra_amount": round(after - within, 2) if within is not None and after is not None else None,
        "late_payment_extra_percent": _pct(after - within, within) if within and after is not None else None,
    }
    energy = [c["amount"] for c in bill.get("charges", []) if c["type"] == "energy"]
    if energy and units:
        m["energy_charges_total"] = round(sum(energy), 2)
        m["energy_cost_per_unit"] = round(sum(energy) / units, 2)
    hist = [u for u in extras.usage_history if u.units is not None]
    prev = [u for u in hist if u.month != bill.get("bill_month")]  # previous months only
    if hist:
        top, low = max(hist, key=lambda u: u.units), min(hist, key=lambda u: u.units)
        m["usage_history_months_including_current"] = len(hist)
        m["usage_history_average_units_including_current"] = round(sum(u.units for u in hist) / len(hist), 1)
        m["usage_history_highest"] = {"month": top.month, "units": top.units}
        m["usage_history_lowest"] = {"month": low.month, "units": low.units}
    if prev and len(prev) < len(hist):  # the current month was found in the history
        avg = round(sum(u.units for u in prev) / len(prev), 1)
        m["previous_months_count"] = len(prev)
        m["previous_months_average_units"] = avg
        if units is not None:
            m["current_units_vs_previous_average_percent"] = _pct(units - avg, avg)
            m["current_units_minus_previous_average"] = round(units - avg, 1)
    m.update(history_analysis(bill, extras, units))
    return {k: v for k, v in m.items() if v is not None}


# ---------- answering ----------
SYSTEM_PROMPT = """You are a friendly assistant that explains a Pakistani electricity bill (K-Electric, LESCO or IESCO)
to the customer in plain English. You are given the bill image, the extracted bill data, extra context read from the
bill, and pre-computed metrics.

Rules:
- Use ONLY information on this bill. Never use outside tariff, rate or policy knowledge. If the bill does not show a
  needed value, say plainly that the bill does not show it instead of guessing.
- Numbers must be exact. Use the pre-computed metrics and the listed monthly values; when you must count or add,
  list the items you counted and double-check the arithmetic before answering.
- When a figure is an estimate or projection, say it is an estimate and show how you calculated it.
- If a question has more than one reasonable meaning (e.g. total vs average, with or without the current month),
  state the meaning you used and also give the number for the other reading.
- Forecast / "should I expect" / "set aside" / "roughly" answers are estimates: say so, give the number, and show the
  method (e.g. average of previous 12 months, same month last year, linear trend) using the pre-computed values.
- To decide whether a connection is net-metered, look for printed evidence (e.g. "Net Metering", export/import
  energy, net metering benefit, a net metering customer type) and cite what you saw.
- Quote amounts as "PKR 1,234.56". Show your working: name the specific bill lines, months and values you relied on
  (e.g. when counting months, list each matching month with its units, and say whether the current month is included).
- Never reveal names, addresses, CNIC, account, consumer, reference or meter numbers.
- Answer in English even if parts of the bill are in Urdu. Be concise and specific: short paragraphs. Plain text only:
  no markdown, no asterisks, no headings, no tables. Use simple "- " lines when listing items."""


class BillAssistant:
    def __init__(self, extractor: BillExtractor, extras_dir: Path):
        self.ex = extractor
        self.extras_dir = extras_dir

    @staticmethod
    def _vote_extras(reads: list[Extras]) -> Extras:
        """Per-month majority vote across reads; a month must appear in a majority of reads to be kept."""
        need = len(reads) // 2 + 1 if len(reads) > 2 else 1
        pick = lambda vals: max(vals, key=lambda v: (vals.count(v), -vals.index(v)))
        usage = []
        for m in sorted({u.month for r in reads for u in r.usage_history}):
            vals = [u.units for r in reads for u in r.usage_history if u.month == m]
            if len(vals) >= need:
                usage.append(UsageMonth(month=m, units=pick(vals)))
        pays = []
        for m in sorted({p.month for r in reads for p in r.payment_history}):
            vals = [(p.billed, p.paid, p.pay_date) for r in reads for p in r.payment_history if p.month == m]
            if len(vals) >= need:
                b, pd, d = pick(vals)
                pays.append(PaymentRecord(month=m, billed=b, paid=pd, pay_date=d))
        notes = next((r.notes for r in reads if r.notes), [])
        return Extras(usage_history=usage, payment_history=pays, notes=notes)

    def get_extras(self, bill_id: str, image_path: Path, reads: int = 3) -> Extras:
        cache = self.extras_dir / f"{bill_id}.json"
        if cache.exists():
            return Extras.model_validate_json(cache.read_text(encoding="utf-8"))

        image, mime = load_image_bytes(image_path)
        parts = [types.Part.from_bytes(data=image, mime_type=mime)]
        parts += [types.Part.from_bytes(data=b, mime_type="image/png") for b in band_images(image_path)]

        def once() -> Extras:
            r = self.ex.client.models.generate_content(
                model=self.ex.settings.model,
                contents=[*parts, EXTRAS_PROMPT],
                config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                                   response_schema=Extras),
            )
            return r.parsed if r.parsed is not None else Extras.model_validate_json(r.text)

        try:
            samples = []
            for _ in range(reads):
                try:
                    samples.append(retry_call(once))
                except Exception as e:
                    if not samples:
                        raise
                    log.warning("%s: history read failed, voting on %d reads: %s", bill_id, len(samples), e)
                    break
            extras = self._vote_extras(samples) if len(samples) > 1 else samples[0]
        except Exception as e:  # history is optional context; degrade instead of failing the answer
            log.warning("%s: could not read history: %s", bill_id, e)
            return Extras()
        self.extras_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(extras.model_dump_json(indent=2), encoding="utf-8")
        return extras

    def answer(self, bill_id: str, image_path: Path, bill: dict, question: str,
               history: list[dict] | None = None) -> str:
        image, mime = load_image_bytes(image_path)
        extras = self.get_extras(bill_id, image_path)
        context = {
            "bill_data": bill,
            "history_and_notes_from_bill": extras.model_dump(),
            "precomputed_metrics": compute_metrics(bill, extras),
        }
        convo = ""
        for turn in (history or [])[-6:]:
            who = "Customer" if turn.get("role") == "user" else "Assistant"
            convo += f"{who}: {str(turn.get('text', ''))[:1200]}\n"
        prompt = (f"BILL CONTEXT (JSON):\n{json.dumps(context, indent=1)}\n\n"
                  + (f"CONVERSATION SO FAR:\n{convo}\n" if convo else "")
                  + f"CUSTOMER QUESTION: {question}\n\nAnswer the question.")

        def once() -> str:
            r = self.ex.client.models.generate_content(
                model=self.ex.settings.model,
                contents=[types.Part.from_bytes(data=image, mime_type=mime), prompt],
                config=types.GenerateContentConfig(temperature=0.2, system_instruction=SYSTEM_PROMPT,
                                                   ),
            )
            if not (r.text or "").strip():
                raise RuntimeError("empty answer")
            return r.text.replace("**", "").replace("__", "").strip()

        return retry_call(once)
