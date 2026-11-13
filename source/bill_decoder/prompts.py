"""Level 1 extraction prompt.

Sections 5.1-5.7 of the task guide are embedded verbatim so the model works from the exact rules it is
scored on. Only the clearly marked "clarifications" block at the end is our own addition.
"""

EXTRACTION_PROMPT = """You are reading an electricity bill image from K-Electric, LESCO or IESCO, as a scan, screenshot or photo.
Layouts vary: some bills are tilted or partly in Urdu, and names, addresses and ID numbers are covered with grey boxes.
Read every digit carefully and extract the bill's details into the JSON schema, following the rules below.
They are the official task rules; follow them exactly.

## 5.1 JSON output format
{
"provider": "KE | LESCO | IESCO",
"tariff": "string",
"sanctioned_load_kw": "number",
"bill_month": "YYYY-MM",
"reading_date": "YYYY-MM-DD",
"issue_date": "YYYY-MM-DD",
"due_date": "YYYY-MM-DD",
"previous_reading": "number",
"current_reading": "number",
"units_consumed": "number",
"charges": [ {"type": "energy | fixed | fpa | quarterly_adjustment | surcharge | meter_rent | subsidy | other", "amount": "number"} ],
"total_charges": "number",
"taxes": [ {"type": "gst | electricity_duty | income_tax | municipal_tax | other_tax", "amount": "number"} ],
"total_taxes": "number",
"current_bill": "number",
"arrears": "number",
"payable_within_due_date": "number",
"payable_after_due_date": "number"
}
Include every field, even when its value is null. Use numbers for numeric fields, not quoted strings.

## 5.2 General extraction rules
- Extract values as printed. Do not recalculate, round, or correct bill amounts.
- Amounts are numbers in PKR. Remove currency labels and commas: Rs. 19,964 becomes 19964.
- Credits and subsidies are negative. For example, 38209CR becomes -38209. Record a subsidy as a deduction.
- Use the required date formats. 22nd Sep 2026 becomes 2026-09-22; MAR 2026 becomes 2026-03.
- Use null for unavailable values: not printed, blank, covered by a grey box, or unreadable. A correct null is
  scored as correct. Do not guess. Use [] for an empty list.
- Exclude personal identifiers. Do not return names, addresses, CNIC, account numbers, reference numbers,
  consumer numbers, or meter numbers.

## 5.3 What to return for each field
- provider: One of KE, LESCO, or IESCO.
- tariff: The tariff code exactly as printed (copy it character for character, keeping letter case).
- sanctioned_load_kw: Sanctioned load in kW, labelled Sanc Load, S.Load, or San Load.
- bill_month: The billing month in YYYY-MM format.
- reading_date, issue_date, due_date: The printed dates in YYYY-MM-DD format. The due date is the last date to pay
  without a late payment surcharge.
- previous_reading, current_reading: The printed meter readings.
- units_consumed: The units billed for the current month, as printed.
- charges: One entry per line in the charges section. Skip blank lines and lines printed as 0. Keep separate
  entries when the same type appears more than once.
- total_charges: The printed charges subtotal, or null if no subtotal is printed.
- taxes: One entry per line in the tax or government section. Classify a line by its section, not its name. If only
  a combined tax amount is printed, return [] and put that amount in total_taxes.
- total_taxes: The printed tax subtotal, or null if no subtotal is printed.
- current_bill: The printed amount for this month's bill.
- arrears: Previous dues carried forward. Keep the printed sign; return null if blank.
- payable_within_due_date: The amount payable by the due date.
- payable_after_due_date: The amount payable after the due date. If several late-payment amounts are shown, use
  the highest.

## 5.4 Charge and tax types
The printed section determines whether a line belongs in charges or taxes.
Charge types (each entry in charges):
- energy: Cost of units used, such as Variable Upto ... Units, Cost of Electricity, or Energy Charges.
- fixed: Fixed charges.
- fpa: Fuel price adjustment. Use fpa for both FPA and FCA.
- quarterly_adjustment: Quarterly tariff adjustment, such as QTA or Uniform Quarterly Adjustment.
- surcharge: Surcharges, such as Additional Surcharge (PHL) or F.C Surcharge.
- meter_rent: Meter rent or service rent.
- subsidy: Government subsidy or relief lines. Record the amount as negative.
- other: Any other charge line.
Tax types (each entry in taxes):
- gst: Sales tax or GST, including GST on FPA.
- electricity_duty: Electricity duty, often labelled ED.
- income_tax: Income tax.
- municipal_tax: Municipal or local charges printed under taxes, such as KE MUCT (KMC).
- other_tax: Any other tax line, such as extra tax, further tax, or TV fee.

## 5.7 Correct JSON for a sample K-Electric bill (shows how printed values map to fields)
{"provider": "KE", "tariff": "A1-R", "sanctioned_load_kw": 3, "bill_month": "2026-04", "reading_date": "2026-04-03",
"issue_date": "2026-04-07", "due_date": "2026-04-21", "previous_reading": 8819, "current_reading": 8970,
"units_consumed": 151,
"charges": [{"type": "fixed", "amount": 900}, {"type": "energy", "amount": 1054}, {"type": "energy", "amount": 663.51},
{"type": "quarterly_adjustment", "amount": 52.91}, {"type": "fpa", "amount": 125.27}, {"type": "surcharge", "amount": 64.93}],
"total_charges": 2860.62,
"taxes": [{"type": "electricity_duty", "amount": 29.41}, {"type": "gst", "amount": 520.21}, {"type": "municipal_tax", "amount": 20}],
"total_taxes": 569.62, "current_bill": 3430.24, "arrears": -0.53, "payable_within_due_date": 3430,
"payable_after_due_date": 3716}
Key points: the bill has two energy-charge lines, so charges includes two energy entries; the printed previous dues
are a credit of PKR 0.53, so arrears is -0.53; the bill shows more than one late-payment amount and the highest,
PKR 3,716, is returned.

## Clarifications (apply the rules above; they do not override them)
- Output "label" for every charge and tax entry: the line's text exactly as printed (English if bilingual).
- Copy the tariff character-for-character: keep letter case, hyphens, parentheses and any trailing letter.
- Any amount printed with a CR suffix (or "Cr"/"credit") is negative in every field, including payable amounts
  ("54770CR" becomes -54770). A printed minus sign stays negative.
- Text such as "NOT TO BE PAID", or a blank/dash where a number belongs, means null for that field.
- If the meter has several registers (e.g. Off Peak / Peak / Import), previous_reading and current_reading come from
  the FIRST register row; units_consumed still comes from the billed-units figure, not from the difference.
- A single line labelled only "Taxes" (or "Total taxes") with one amount and no named components is a combined tax
  amount: taxes = [] and that amount goes in total_taxes.
- LESCO/IESCO layouts: "Total Electricity Charges" / "Cost of Electricity" is an energy line; a non-zero "Subsidies"
  line is a subsidy (negative); the "Net Electricity Charges" amount is total_charges. Never leave charges empty when a
  charges amount is printed.
- In a "Bill charges breakdown" block, current_bill is the row labelled "Current Bill" (net charges + taxes), NOT the
  "Grand Total" (which also adds arrears, FPA or other items). total_taxes is the amount on the "Taxes" row; a
  percentage printed next to it (e.g. "22.22%") is not the amount. Handwritten notes on the bill are not bill values.
- Some bills print FPA (e.g. "Total FPA") below the charges subtotal. It is still a charge line of type fpa.

Return only the JSON object.
"""

RETRY_SUFFIX = """
A previous attempt had these inconsistencies with the printed bill. Re-read the image carefully at those
spots and correct genuine misreads of the image. If the bill itself is inconsistent, keep the values AS PRINTED.
Issues:
{issues}
"""
