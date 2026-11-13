"""Level 1: bill image -> validated Bill JSON using a Gemini vision model."""
import io
import json
import logging
import re
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image, ImageOps

from .config import Settings, load_settings
from .llm import retry_call, set_fallback
from .prompts import EXTRACTION_PROMPT, RETRY_SUFFIX
from .schema import Bill

log = logging.getLogger("bill_decoder")

MAX_SIDE = 3000   # downscale huge photos; keeps small print legible
MIN_SIDE = 1600   # upscale tiny screenshots so digits are readable
TOLERANCE = 1.0   # scoring accepts +-1 on numbers


def load_image_bytes(path: Path) -> tuple[bytes, str]:
    """Fix EXIF rotation, normalise size, return PNG bytes."""
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    longest = max(img.size)
    if longest > MAX_SIDE or longest < MIN_SIDE:
        scale = (MAX_SIDE if longest > MAX_SIDE else MIN_SIDE) / longest
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), "image/png"


def check_consistency(b: Bill) -> list[str]:
    """Cross-check printed numbers; returns human-readable issues (empty = fine)."""
    issues: list[str] = []
    if b.previous_reading is not None and b.current_reading is not None and b.units_consumed is not None:
        diff = b.current_reading - b.previous_reading
        # Multiplier/MDI meters can legitimately differ, so only flag, never overwrite.
        if abs(diff - b.units_consumed) > TOLERANCE and b.units_consumed > 0:
            issues.append(f"current_reading - previous_reading = {diff:g} but units_consumed = {b.units_consumed:g}")
    if not b.charges and b.total_charges:
        issues.append(f"charges list is empty but total_charges = {b.total_charges:g}; list the printed charge lines")
    if b.total_charges is not None and b.charges:
        s = sum(c.amount for c in b.charges)
        tol = max(TOLERANCE, 0.01 * abs(b.total_charges))
        # Some bills print FPA below the charges subtotal; that is a layout quirk, not a misread.
        fpa_outside = any(c.type == "fpa" and abs(s - c.amount - b.total_charges) <= tol for c in b.charges)
        if abs(s - b.total_charges) > tol and not fpa_outside:
            issues.append(f"charges sum to {s:.2f} but total_charges = {b.total_charges:g}")
    if b.total_taxes is not None and b.taxes:
        s = sum(t.amount for t in b.taxes)
        if abs(s - b.total_taxes) > max(TOLERANCE, 0.01 * abs(b.total_taxes)):
            issues.append(f"taxes sum to {s:.2f} but total_taxes = {b.total_taxes:g}")
    if None not in (b.total_charges, b.total_taxes, b.current_bill):
        if abs(b.total_charges + b.total_taxes - b.current_bill) > 2 * TOLERANCE:
            issues.append(f"total_charges + total_taxes = {b.total_charges + b.total_taxes:g} but current_bill = "
                          f"{b.current_bill:g}; current_bill should be the 'Current Bill' amount (this month's "
                          f"charges plus taxes), not a grand total that also adds arrears or other items")
    if (b.payable_within_due_date is not None and b.payable_after_due_date is not None
            and b.payable_after_due_date + TOLERANCE < b.payable_within_due_date):
        issues.append("payable_after_due_date is lower than payable_within_due_date (should be the highest late amount)")
    return issues


_GENERIC_TAX = re.compile(r"^\s*(total\s+)?(govt\.?\s+|government\s+)?(tax(es)?|taxes\s*&\s*duties)\s*:?\s*$", re.I)


# Printed-label rules. They override the model's type only on an unambiguous match, which fixes the
# occasional "Uniform Quarterly Adjustment" -> fpa style slip. Order matters (first match wins).
_CHARGE_RULES = [
    (r"\bquarterly|\bqta\b|\buqa\b", "quarterly_adjustment"),
    (r"surcharge", "surcharge"),
    (r"\bfpa\b|\bfca\b|fuel\s*(price|charges?)\s*adj", "fpa"),
    (r"meter\s*rent|service\s*rent", "meter_rent"),
    (r"subsid|relief", "subsidy"),
    (r"\bfixed\b", "fixed"),
    (r"variable|energy\s*charge|cost\s*of\s*electricity|electricity\s*charges|\bunits?\b", "energy"),
]
_TAX_RULES = [
    (r"income\s*tax", "income_tax"),
    (r"\bmuct\b|\bkmc\b|municipal", "municipal_tax"),
    (r"electricity\s*duty|^\s*e\.?d\.?\s*$", "electricity_duty"),
    (r"sales\s*tax|\bgst\b", "gst"),
]


def _retype(items, rules) -> None:
    for it in items:
        label = (it.label or "").lower()
        for pattern, typ in rules:
            if re.search(pattern, label):
                it.type = typ
                break


def normalise(b: Bill) -> Bill:
    """Deterministic clean-ups that never change printed amounts."""
    # A lone generic "Taxes" line is a combined amount: taxes = [], amount goes to total_taxes.
    if len(b.taxes) == 1 and b.taxes[0].label and _GENERIC_TAX.match(b.taxes[0].label):
        if b.total_taxes is None:
            b.total_taxes = b.taxes[0].amount
        b.taxes = []
    # Row-shift misread: current_bill holds the grand total (== amount payable) while total_taxes holds the real
    # "Current Bill" (total_taxes + arrears reaches the payable amount). The tax amount itself is then unknown.
    if (None not in (b.total_taxes, b.current_bill, b.payable_within_due_date) and b.arrears
            and abs(b.current_bill - b.payable_within_due_date) <= TOLERANCE
            and abs(b.payable_within_due_date - (b.total_taxes + b.arrears)) <= 0.03 * abs(b.payable_within_due_date)
            and b.total_taxes > (b.total_charges or 0)):
        b.current_bill, b.total_taxes, b.taxes = b.total_taxes, None, []
    # A tax subtotal equal to the whole bill while the charges are listed separately is a misread
    # (typically the neighbouring "Current Bill" figure); an unreadable value must be null, not a guess.
    if (b.total_taxes is not None and b.current_bill and b.total_charges
            and abs(b.total_taxes - b.current_bill) <= 0.5 and b.total_charges > 0.5):
        b.total_taxes = None
        b.taxes = []
    _retype(b.charges, _CHARGE_RULES)
    _retype(b.taxes, _TAX_RULES)
    b.charges = [c for c in b.charges if c.amount != 0]
    b.taxes = [t for t in b.taxes if t.amount != 0]
    for c in b.charges:
        if c.type == "subsidy" and c.amount > 0:
            c.amount = -c.amount
    if b.bill_month and len(b.bill_month) >= 7:
        b.bill_month = b.bill_month[:7]
    return b


class BillExtractor:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()
        if self.settings.provider != "google":
            raise NotImplementedError("Level 1 currently supports MODEL_PROVIDER=google")
        self.client = genai.Client(api_key=self.settings.api_key)
        self._on_fallback = False
        if self.settings.fallback_key:
            set_fallback(self._use_fallback)

    def _use_fallback(self) -> bool:
        """Swap to the backup key once (called by retry_call after repeated quota errors)."""
        if self._on_fallback:
            return False
        self.client = genai.Client(api_key=self.settings.fallback_key)
        self._on_fallback = True
        return True

    def _call(self, image: bytes, mime: str, prompt: str) -> Bill:
        def once() -> Bill:
            resp = self.client.models.generate_content(
                model=self.settings.model,
                contents=[types.Part.from_bytes(data=image, mime_type=mime), prompt],
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                    response_schema=Bill,
                ),
            )
            return resp.parsed if resp.parsed is not None else Bill.model_validate_json(resp.text)

        return retry_call(once)

    def _read_once(self, image: bytes, mime: str, name: str) -> Bill:
        """One full read: model call, consistency check, and a single targeted re-read if needed."""
        bill = normalise(self._call(image, mime, EXTRACTION_PROMPT))
        issues = check_consistency(bill)
        if issues:
            log.info("%s: re-reading, issues: %s", name, issues)
            prompt = EXTRACTION_PROMPT + RETRY_SUFFIX.format(issues=chr(10).join(f"- {i}" for i in issues))
            retry = normalise(self._call(image, mime, prompt))
            # Accept only a strictly better read that did not simply blank out fields to dodge the checks.
            if len(check_consistency(retry)) < len(issues) and _filled(retry) >= _filled(bill):
                bill = retry
        return bill

    def extract(self, path: Path, samples: int = 2) -> tuple[Bill, list[str]]:
        """Read the bill up to `samples`+1 times and take a field-wise majority vote.

        Two reads are taken; a third only if they disagree. Returns (bill, remaining_issues).
        """
        image, mime = load_image_bytes(path)
        reads = [self._read_once(image, mime, path.stem)]
        for _ in range(samples - 1):
            reads.append(self._read_once(image, mime, path.stem))
        if len(reads) > 1 and len({json.dumps(r.public(), sort_keys=True) for r in reads}) > 1:
            reads.append(self._read_once(image, mime, path.stem))
        bill = _vote(reads) if len(reads) > 1 else reads[0]
        return bill, check_consistency(bill)


def _filled(b: Bill) -> int:
    d = b.public()
    return sum(v is not None for k, v in d.items() if k not in ("charges", "taxes")) + len(d["charges"]) + len(d["taxes"])


def _vote(reads: list[Bill]) -> Bill:
    """Field-wise majority vote; ties go to the earliest read."""
    dumps = [r.public() for r in reads]
    out = {}
    for key in dumps[0]:
        vals = [json.dumps(d[key], sort_keys=True) for d in dumps]
        best = max(vals, key=lambda v: (vals.count(v), -vals.index(v)))
        out[key] = json.loads(best)
    return Bill.model_validate(out)
