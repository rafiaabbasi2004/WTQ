"""Score Level 1 extraction against reference answers, using the guide's rules
(text/dates exact, numbers within +-1).  Runs each bill N times to expose instability.

  python evaluate.py --bills ../data/train/bills --runs 3
"""
import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path

from bill_decoder.extract import BillExtractor

FIELDS = ["provider", "tariff", "sanctioned_load_kw", "bill_month", "reading_date", "issue_date", "due_date",
          "previous_reading", "current_reading", "units_consumed", "charges", "total_charges", "taxes",
          "total_taxes", "current_bill", "arrears", "payable_within_due_date", "payable_after_due_date"]


def num_ok(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= 1


def field_ok(name: str, pred, truth) -> bool:
    if name in ("charges", "taxes"):
        return (isinstance(pred, list) and len(pred) == len(truth)
                and all(p["type"] == t["type"] and num_ok(p["amount"], t["amount"]) for p, t in zip(pred, truth)))
    if isinstance(truth, (int, float)) or truth is None:
        return num_ok(pred, truth)
    return pred == truth


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bills", type=Path, required=True)
    ap.add_argument("--reference", type=Path, default=Path("eval/reference.json"))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--only", nargs="*", help="evaluate only these bill ids")
    ap.add_argument("--out", type=Path, default=Path("../output/eval_runs.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)

    ref = {k: v for k, v in json.loads(args.reference.read_text(encoding="utf-8")).items() if not k.startswith("_") and (not args.only or k in args.only)}
    files = {p.stem: p for p in args.bills.iterdir()}
    ex = BillExtractor()

    runs: dict[str, list[dict]] = {}
    for bill_id in ref:
        runs[bill_id] = []
        for i in range(args.runs):
            bill, _ = ex.extract(files[bill_id])
            runs[bill_id].append(bill.public())
            print(f"  ran {bill_id} #{i + 1}", flush=True)
    args.out.write_text(json.dumps(runs, indent=1), encoding="utf-8")

    per_field = defaultdict(lambda: [0, 0])
    print("\nPer bill (fields correct per run):")
    for bill_id, truth in ref.items():
        scores = []
        for pred in runs[bill_id]:
            ok = [f for f in FIELDS if field_ok(f, pred.get(f), truth[f])]
            scores.append(len(ok))
            for f in FIELDS:
                per_field[f][1] += 1
                per_field[f][0] += f in ok
        wrong = sorted({f for pred in runs[bill_id] for f in FIELDS if not field_ok(f, pred.get(f), truth[f])})
        print(f"  {bill_id}: {scores} / {len(FIELDS)}   wrong at least once: {wrong or '-'}")

    total_ok = sum(v[0] for v in per_field.values())
    total = sum(v[1] for v in per_field.values())
    print(f"\nOverall: {total_ok}/{total} = {total_ok / total:.1%}")
    bad = {f: f"{a}/{b}" for f, (a, b) in per_field.items() if a < b}
    print("Fields not always correct:", bad or "none")


if __name__ == "__main__":
    main()
