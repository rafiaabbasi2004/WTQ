"""Generate level1.csv and level2.csv for a folder of bills.

Examples
  # Test set (templates supplied by the organisers)
  python run_all.py --bills ../data/test/bills --level1-template ../data/test/csv/level1.csv \
                    --level2-template ../data/test/csv/level2.csv --out-dir ../output

  # Quick look at Level 1 only, no templates needed
  python run_all.py --bills ../data/train/bills --level1-only
"""
import argparse
import csv
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bill_decoder.extract import BillExtractor
from bill_decoder.qa import BillAssistant
from bill_decoder.schema import Bill

log = logging.getLogger("run_all")
EXTS = {".png", ".jpg", ".jpeg"}
FALLBACK_ANSWER = "I could not determine this reliably from the bill image, so I would rather not guess."


def read_template(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(rows)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bills", required=True, type=Path, help="folder of bill images (.png/.jpg)")
    ap.add_argument("--level1-template", type=Path)
    ap.add_argument("--level2-template", type=Path)
    ap.add_argument("--out-dir", type=Path, default=Path("../output"))
    ap.add_argument("--level1-only", action="store_true")
    ap.add_argument("--workers", type=int, default=4, help="parallel Level 2 questions")
    ap.add_argument("--fresh", action="store_true", help="ignore cached per-bill results")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)

    images = {p.stem: p for p in sorted(args.bills.iterdir()) if p.suffix.lower() in EXTS}
    if not images:
        raise SystemExit(f"no bill images found in {args.bills}")
    out = args.out_dir
    l1_cache, l2_cache = out / "level1_json", out / "level2_answers.json"
    l1_cache.mkdir(parents=True, exist_ok=True)

    extractor = BillExtractor()

    # ---------------- Level 1 ----------------
    bills: dict[str, dict] = {}
    for bill_id, path in images.items():
        cache = l1_cache / f"{bill_id}.json"
        data = None if args.fresh else load_json(cache, None)
        if data is None:
            try:
                bill, issues = extractor.extract(path)
                data = bill.public()
                for i in issues:
                    log.warning("%s: %s", bill_id, i)
            except Exception as e:  # keep the run going; an all-null record is better than a crash
                log.error("%s: extraction failed: %s", bill_id, e)
                data = Bill().public()
            else:
                cache.write_text(json.dumps(data, indent=2), encoding="utf-8")
        bills[bill_id] = data
        log.info("level 1 done: %s", bill_id)

    rows1 = read_template(args.level1_template) if args.level1_template else [{"bill_id": b} for b in bills]
    write_csv(out / "level1.csv", ["bill_id", "json"], [
        {"bill_id": r["bill_id"],
         "json": json.dumps(bills.get(r["bill_id"]) or Bill().public(), separators=(",", ":"))}
        for r in rows1])
    log.info("wrote %s (%d rows)", out / "level1.csv", len(rows1))
    if args.level1_only:
        return
    if not args.level2_template:
        raise SystemExit("--level2-template is required unless --level1-only is set")

    # ---------------- Level 2 ----------------
    assistant = BillAssistant(extractor, out / "extras_json")
    answers: dict[str, str] = {} if args.fresh else load_json(l2_cache, {})
    rows2 = read_template(args.level2_template)

    # Warm the per-bill history extraction once (sequentially) so parallel questions never duplicate it.
    for bill_id in dict.fromkeys(r["bill_id"] for r in rows2):
        if bill_id in images:
            assistant.get_extras(bill_id, images[bill_id])

    lock = threading.Lock()
    todo = [r for r in rows2 if not answers.get(f"{r['bill_id']}|{r['question_id']}")]

    def work(r: dict) -> None:
        key = f"{r['bill_id']}|{r['question_id']}"
        path, data = images.get(r["bill_id"]), bills.get(r["bill_id"])
        if path is None or data is None:
            answers[key] = FALLBACK_ANSWER
            return
        try:
            text = assistant.answer(r["bill_id"], path, data, r["question"])
        except Exception as e:  # filled with the fallback when writing; retried on the next run
            log.error("%s %s failed: %s", r["bill_id"], r["question_id"], e)
            return
        with lock:
            answers[key] = text
            l2_cache.write_text(json.dumps(answers, indent=1), encoding="utf-8")  # resume-safe
        log.info("level 2 done: %s %s", r["bill_id"], r["question_id"])

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, todo))

    write_csv(out / "level2.csv", ["bill_id", "question_id", "question", "answer"], [
        {"bill_id": r["bill_id"], "question_id": r["question_id"], "question": r["question"],
         "answer": answers.get(f"{r['bill_id']}|{r['question_id']}") or FALLBACK_ANSWER}
        for r in rows2])
    missing = sum(1 for r in rows2 if not answers.get(f"{r['bill_id']}|{r['question_id']}"))
    log.info("wrote %s (%d rows, %d used the fallback answer)", out / "level2.csv", len(rows2), missing)


if __name__ == "__main__":
    main()
