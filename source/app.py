"""Dashboard backend.  Run:  uvicorn app:app --reload   (from the source/ folder)"""
import json
import logging
import re
import shutil
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bill_decoder.extract import BillExtractor, check_consistency
from bill_decoder.qa import BillAssistant
from bill_decoder.schema import Bill

log = logging.getLogger("dashboard")
ROOT = Path(__file__).resolve().parent.parent
BILL_DIRS = [ROOT / "data" / "train" / "bills", ROOT / "data" / "test" / "bills", ROOT / "output" / "uploads"]
CACHE = ROOT / "output" / "level1_json"
EXTS = {".png", ".jpg", ".jpeg"}

app = FastAPI(title="Utility Bill Decoder")
_extractor: BillExtractor | None = None
_assistant: BillAssistant | None = None
_lock = threading.Lock()


def extractor() -> BillExtractor:
    global _extractor
    with _lock:
        if _extractor is None:
            _extractor = BillExtractor()
        return _extractor


def assistant() -> BillAssistant:
    global _assistant
    ex = extractor()
    with _lock:
        if _assistant is None:
            _assistant = BillAssistant(ex, ROOT / "output" / "extras_json")
        return _assistant


def find_bills() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for d in BILL_DIRS:
        if d.exists():
            for p in sorted(d.iterdir()):
                if p.suffix.lower() in EXTS:
                    found.setdefault(p.stem, p)
    return found


def cached(bill_id: str) -> dict | None:
    f = CACHE / f"{bill_id}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def run_extraction(bill_id: str, path: Path) -> dict:
    try:
        bill, issues = extractor().extract(path)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    data = bill.public()
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"{bill_id}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def payload(bill_id: str, data: dict) -> dict:
    return {"id": bill_id, "data": data, "issues": check_consistency(Bill.model_validate(data))}


@app.get("/api/bills")
def list_bills():
    def source(p: Path) -> str:
        return {"train": "train", "test": "test"}.get(p.parent.parent.name, "upload")

    return [{"id": k, "source": source(p), "extracted": (CACHE / f"{k}.json").exists(),
             "provider": (cached(k) or {}).get("provider") or k.split("_")[0].replace("KESC", "KE")}
            for k, p in find_bills().items()]


@app.get("/api/bills/{bill_id}")
def get_bill(bill_id: str, refresh: bool = False):
    path = find_bills().get(bill_id)
    if not path:
        raise HTTPException(404, "bill not found")
    data = None if refresh else cached(bill_id)
    return payload(bill_id, data or run_extraction(bill_id, path))


@app.get("/api/bills/{bill_id}/image")
def bill_image(bill_id: str):
    path = find_bills().get(bill_id)
    if not path:
        raise HTTPException(404, "bill not found")
    return FileResponse(path)


@app.post("/api/upload")
def upload(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in EXTS:
        raise HTTPException(400, "Upload a .png or .jpg bill image")
    base = re.sub(r"[^A-Za-z0-9_-]", "_", Path(file.filename).stem)[:30] or "bill"
    stem = f"{base}_{uuid.uuid4().hex[:6]}"  # unique per upload so users never collide
    dest_dir = ROOT / "output" / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{stem}{suffix}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return payload(stem, run_extraction(stem, dest))


class AskBody(BaseModel):
    question: str
    history: list[dict] = []


@app.post("/api/bills/{bill_id}/ask")
def ask(bill_id: str, body: AskBody):
    path = find_bills().get(bill_id)
    if not path:
        raise HTTPException(404, "bill not found")
    if not body.question.strip():
        raise HTTPException(400, "question is empty")
    data = cached(bill_id) or run_extraction(bill_id, path)
    try:
        answer = assistant().answer(bill_id, path, data, body.question.strip(), body.history)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    return {"answer": answer}


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
