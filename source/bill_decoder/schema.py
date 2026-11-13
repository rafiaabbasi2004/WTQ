"""Level 1 output schema (guide section 5.1)."""
from typing import Literal, Optional

from pydantic import BaseModel

ChargeType = Literal[
    "energy", "fixed", "fpa", "quarterly_adjustment",
    "surcharge", "meter_rent", "subsidy", "other",
]
TaxType = Literal["gst", "electricity_duty", "income_tax", "municipal_tax", "other_tax"]


class Charge(BaseModel):
    type: ChargeType
    amount: float
    label: Optional[str] = None   # line text as printed; used internally, never emitted


class Tax(BaseModel):
    type: TaxType
    amount: float
    label: Optional[str] = None


class Bill(BaseModel):
    provider: Optional[Literal["KE", "LESCO", "IESCO"]] = None
    tariff: Optional[str] = None
    sanctioned_load_kw: Optional[float] = None
    bill_month: Optional[str] = None      # YYYY-MM
    reading_date: Optional[str] = None    # YYYY-MM-DD
    issue_date: Optional[str] = None
    due_date: Optional[str] = None
    previous_reading: Optional[float] = None
    current_reading: Optional[float] = None
    units_consumed: Optional[float] = None
    charges: list[Charge] = []
    total_charges: Optional[float] = None
    taxes: list[Tax] = []
    total_taxes: Optional[float] = None
    current_bill: Optional[float] = None
    arrears: Optional[float] = None
    payable_within_due_date: Optional[float] = None
    payable_after_due_date: Optional[float] = None

    def public(self) -> dict:
        """The Level 1 JSON exactly as specified (no internal label fields)."""
        d = self.model_dump()
        for k in ("charges", "taxes"):
            d[k] = [{"type": x["type"], "amount": x["amount"]} for x in d[k]]
        return d
