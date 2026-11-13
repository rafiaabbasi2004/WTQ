# Utility Bill Decoder

An AI assistant that reads a Pakistani electricity bill image (K-Electric, LESCO, IESCO), extracts its details as
JSON (Level 1) and answers customer questions about it in plain English (Level 2).

- **Runtime:** Python 3.11 (developed on 3.11.1). Node.js 20+ is only needed to rebuild the optional web UI.
- **Model:** `gemini-3.5-flash-lite` (Google Gemini API, one of the allowed models).

## Setup

```bash
cd source
python -m venv .venv
.venv/Scripts/activate            # Windows;  macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # then put your Gemini API key in API_KEY
```

`.env` variables (see `.env.example`): `MODEL_PROVIDER=google`, `MODEL_NAME=gemini-3.5-flash-lite`, `API_KEY`,
optional `MAX_RPM`, and optional `FALLBACK_KEY` (a second Gemini key used automatically if the main key hits its
quota).

## Generate the result files

```bash
python run_all.py \
  --bills ../data/test/bills \
  --level1-template ../data/test/csv/level1.csv \
  --level2-template ../data/test/csv/level2.csv \
  --out-dir ../output
```

This writes `output/level1.csv` (one JSON object per bill) and `output/level2.csv` (one answer per bill/question).
(Place the downloaded `test/` folder at `data/test/`, or point the paths at wherever you put it.)
Progress is cached (`output/level1_json/`, `output/level2_answers.json`), so an interrupted run resumes where it
stopped; add `--fresh` to recompute everything. `--level1-only` skips question answering.

## Tests

```bash
python -m unittest discover -s tests -v     # deterministic rules, consistency checks, voting, metrics; no API key needed
python evaluate.py --bills ../data/train/bills --runs 3   # Level 1 accuracy vs eval/reference.json (uses the API)
```

## Web UI (used for the demo)

```bash
uvicorn app:app --port 8000       # then open http://localhost:8000
```

A ChatGPT-style interface: upload a bill photo, get a summary card (amount due, due date, units, charges, taxes) and
a plain-language explanation, then ask follow-up questions. The React source is in `frontend/`; the production
build is committed in `static/`. To rebuild: `cd frontend && npm install && npm run build`.

## How it works

1. **Level 1 extraction** (`bill_decoder/extract.py`): the guide's rules are embedded verbatim in the prompt
   (`prompts.py`), and the image (EXIF-rotated, resized) is sent to Gemini with a strict JSON schema. Every charge/tax
   line also returns its printed label. Deterministic code then (a) maps each line to its type from the printed label
   within the section the model placed it in, (b) collapses a lone generic "Taxes" line into `total_taxes`, (c) drops
   zero lines, (d) cross-checks readings vs units, line items vs printed subtotals, and charges + taxes vs the
   current bill, and (e) nulls or repairs a few implausible misreads (e.g. a tax subtotal equal to the whole bill, or
   the grand total read as the current bill). If a check fails the bill is re-read once with the specific
   inconsistency, accepting the retry only if it is strictly better. Each bill is read twice (a third time if the
   reads differ) and the fields are majority-voted. Printed values are never recalculated or "corrected".
2. **Level 2 answers** (`bill_decoder/qa.py`): the usage and payment history tables on the bill are read separately
   (three reads, majority-voted per month, because these tables are often two column groups side by side). The model is
   then given the bill image, the Level 1 JSON, that history, and metrics computed in code: tax share, cost per unit,
   late-payment extra, previous-month averages, same month last year, summer vs winter totals, 3-month trend,
   forecast candidates, payment status. The prompt forbids outside tariff knowledge, requires estimates to be labelled
   with their method, and requires ambiguity to be explained (both readings are given). Questions run in parallel.
3. **Resilience:** requests are rate-limited (`MAX_RPM`; `--workers` sets Level 2 parallelism), transient errors are retried with backoff, a failed bill
   becomes an all-null record rather than crashing the run, and a failed answer gets an explicit "could not
   determine" message instead of an empty cell.

## Project layout

```
run_all.py            CLI: bills + templates -> level1.csv / level2.csv
tests/                unit tests for the deterministic parts
evaluate.py           scores Level 1 against eval/reference.json (repeated runs, per-field accuracy)
eval/reference.json   reference answers for the training bills (KESC_0008 official, others hand-written)
app.py                FastAPI backend for the web UI
bill_decoder/         config, schema, prompts, extract (Level 1), qa (Level 2), llm (retry/rate limit)
frontend/             React + Vite source of the web UI
static/               built web UI served by app.py
```

## AI usage

- **Models used at runtime:** Google `gemini-3.5-flash-lite` (via the Gemini API) for bill reading, history
  extraction and question answering. No other LLM is called.
- **Services / APIs:** Google Gemini API only. No OCR service and no invoice/receipt extraction service is used.
- **Local libraries:** Pillow (image normalisation), Pydantic (schema validation), FastAPI/Uvicorn (web UI),
  React/Vite (frontend).
- **AI tools used to write the code:** Claude Code (Claude Sonnet 5.5, Anthropic).
