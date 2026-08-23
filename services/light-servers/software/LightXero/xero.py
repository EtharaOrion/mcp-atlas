import random
from typing import Dict, List, Any
from pathlib import Path
import yaml
import sys
from datetime import datetime

WORK_DIR = Path('.').__str__()
if WORK_DIR not in sys.path:
    sys.path.append(WORK_DIR)

from software.utils.core import OSConnector, DummyOSConnector
from software.utils.world_snapshot import restore_into, seed_mode, resolve_seed
from software.utils.time import TimeMachine

CORPUS_PATH = Path(__file__).resolve().parent / "corpus"


def _to_bool(v) -> bool:
    return str(v).strip().lower() == "true"


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _opt_float(v, default=None):
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class XeroSession:
    """Deterministic sandbox for the Xero Accounting API mock, ported from the FastAPI service."""

    def __init__(self, os_cfg, seed=None):
        # Seedless: world loaded verbatim from a frozen snapshot next to
        # this module; `seed` is accepted for client compat and ignored.
        if seed_mode():
            # Seed architecture: world rolled from a seed (re-armed).
            self.rng = random.Random(resolve_seed(seed))
            self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()
            self.time_machine = TimeMachine(rng=self.rng)

            from software.utils.world_data import load_state as _load_state
            _load_state(self, 'LightXero')
        else:
            # Seedless: world loaded verbatim from the frozen snapshot.
            restore_into(self, Path(__file__).resolve().parent / "world.pkl")
            self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()

    def get_session_dict(self):
        return {"invoices": self.invoices}

    # --- helpers -----------------------------------------------------------
    def _now(self) -> str:
        return self.os.now()

    def uuid(self) -> str:
        alphabet = "0123456789abcdef"
        h = ''.join(self.rng.choices(alphabet, k=32))
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"

    def _serialize_contact(self, c):
        return {
            "ContactID": c["ContactID"],
            "Name": c["Name"],
            "FirstName": c["FirstName"],
            "LastName": c["LastName"],
            "EmailAddress": c["EmailAddress"],
            "IsCustomer": c["IsCustomer"],
            "IsSupplier": c["IsSupplier"],
            "ContactStatus": c["ContactStatus"],
            "AccountNumber": c["AccountNumber"],
        }

    def _serialize_account(self, a):
        return dict(a)

    def _serialize_invoice(self, inv):
        return {
            "InvoiceID": inv["InvoiceID"],
            "InvoiceNumber": inv["InvoiceNumber"],
            "Type": inv["Type"],
            "Contact": {"ContactID": inv["contact_id"], "Name": inv["contact_name"]},
            "Date": inv["Date"],
            "DueDate": inv["DueDate"],
            "Status": inv["Status"],
            "LineAmountTypes": inv["LineAmountTypes"],
            "SubTotal": inv["SubTotal"],
            "TotalTax": inv["TotalTax"],
            "Total": inv["Total"],
            "AmountDue": inv["AmountDue"],
            "AmountPaid": inv["AmountPaid"],
            "CurrencyCode": inv["CurrencyCode"],
            "Reference": inv["Reference"],
        }

    # --- Invoices ----------------------------------------------------------
    def list_invoices(self, status: str | None = None, type_: str | None = None) -> Dict[str, Any]:
        invoices = list(self.invoices)
        if status:
            invoices = [i for i in invoices if i["Status"].upper() == status.upper()]
        if type_:
            invoices = [i for i in invoices if i["Type"].upper() == type_.upper()]
        return {"status": "ok", "output": {"Invoices": [self._serialize_invoice(i) for i in invoices]}}

    def get_invoice(self, invoice_id: str) -> Dict[str, Any]:
        for i in self.invoices:
            if i["InvoiceID"] == invoice_id or i["InvoiceNumber"] == invoice_id:
                return {"status": "ok", "output": {"Invoices": [self._serialize_invoice(i)]}}
        return {"status": "failed", "output": {"error": "invoice not found", "message": f"Invoice {invoice_id} not found"}}

    def create_invoice(self, contact_id: str, line_items: List[Dict[str, Any]] | None = None,
                       type_: str = "ACCREC", date: str | None = None, due_date: str | None = None,
                       status: str = "DRAFT", reference: str = "",
                       currency_code: str = "USD") -> Dict[str, Any]:
        contact = next((c for c in self.contacts if c["ContactID"] == contact_id), None)
        if not contact:
            return {"status": "failed", "output": {"error": "contact not found", "message": f"Contact {contact_id} not found"}}
        sub_total = 0.0
        for li in (line_items or []):
            qty = _to_float(li.get("Quantity", 1))
            unit = _to_float(li.get("UnitAmount", 0))
            sub_total += qty * unit
        sub_total = round(sub_total, 2)
        total_tax = round(sub_total * 0.10, 2)
        total = round(sub_total + total_tax, 2)
        existing = [i for i in self.invoices if i["Type"] == "ACCREC"]
        next_num = 2047 + len([i for i in existing if i["InvoiceNumber"].startswith("INV-")])
        inv = {
            "InvoiceID": self.uuid(),
            "InvoiceNumber": f"INV-{next_num}",
            "Type": type_ or "ACCREC",
            "contact_id": contact_id,
            "contact_name": contact["Name"],
            "Date": date or self._now()[:10],
            "DueDate": due_date or "",
            "Status": status or "DRAFT",
            "LineAmountTypes": "Exclusive",
            "SubTotal": sub_total,
            "TotalTax": total_tax,
            "Total": total,
            "AmountDue": total,
            "AmountPaid": 0.0,
            "CurrencyCode": currency_code or "USD",
            "Reference": reference or "",
        }
        self.invoices.append(inv)
        return {"status": "ok", "output": {"Invoices": [self._serialize_invoice(inv)]}}

    # --- Contacts ----------------------------------------------------------
    def list_contacts(self) -> Dict[str, Any]:
        return {"status": "ok", "output": {"Contacts": [self._serialize_contact(c) for c in self.contacts]}}

    # --- Accounts ----------------------------------------------------------
    def list_accounts(self) -> Dict[str, Any]:
        return {"status": "ok", "output": {"Accounts": [self._serialize_account(a) for a in self.accounts]}}


if __name__ == "__main__":
    s = XeroSession(seed=12)
    print(s.list_invoices())
    print(s.list_accounts())
