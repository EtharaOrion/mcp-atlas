import random
import re
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

REALM_ID = "4620816365272861350"


def _to_bool(v) -> bool:
    return str(v).strip().lower() == "true"


class QuickbooksSession:
    """Deterministic sandbox for the QuickBooks Online mock, ported from the FastAPI service.

    State is loaded from the corpus at init; subsequent calls read and mutate the
    in-memory tables so repeated calls within a session stay consistent.
    """

    def __init__(self, os_cfg, seed=None, fixture=None):
        # Seedless: world loaded verbatim from a frozen snapshot next to
        # this module; `seed` is accepted for client compat and ignored.
        if seed_mode():
            # Seed architecture: world rolled from a seed (re-armed).
            self.rng = random.Random(resolve_seed(seed))
            self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()
            self.time_machine = TimeMachine(rng=self.rng)

            # World data loaded verbatim from corpus/state.json (no cooking).
            from software.utils.world_data import load_state as _load_state
            _load_state(self, "LightQuickBooks")

            from software.utils.fixtures import apply as _apply_fixtures
            _apply_fixtures(self, "LightQuickBooks", fixture)
        else:
            # Seedless: world loaded verbatim from the frozen snapshot.
            restore_into(self, Path(__file__).resolve().parent / "world.pkl")
            self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()

    def get_session_dict(self):
        return {
            "customers": self.customers,
            "vendors": self.vendors,
            "items": self.items,
            "invoices": self.invoices,
            "bills": self.bills,
            "payments": self.payments,
            "estimates": self.estimates,
            "expenses": self.expenses,
        }

    # --- helpers -----------------------------------------------------------
    def _now(self) -> str:
        return self.os.now()

    def uuid(self) -> str:
        alphabet = "0123456789"
        return ''.join(self.rng.choices(alphabet, k=16))

    def _coerce_item(self, r: Dict[str, Any]) -> Dict[str, Any]:
        now = self._now()
        return {
            "Id": r["Id"],
            "Name": r["Name"],
            "Description": (str(r.get("Description") or "") or None),
            "Type": r["Type"],
            "UnitPrice": float(str(r["UnitPrice"]).strip()),
            "IncomeAccountRef": {
                "value": r["IncomeAccountRef_value"],
                "name": r["IncomeAccountRef_name"],
            },
            "Active": _to_bool(r["Active"]),
            "Taxable": _to_bool(r["Taxable"]),
            "MetaData": {"CreateTime": now, "LastUpdatedTime": now},
            "SyncToken": "0",
        }

    def _table(self, name: str) -> List[Dict[str, Any]]:
        return getattr(self, name)

    def _next_int_id(self, table_name: str) -> int:
        ids = []
        for row in self._table(table_name):
            try:
                ids.append(int(row.get("Id", "0")))
            except (TypeError, ValueError):
                continue
        return (max(ids) + 1) if ids else 1

    def _get(self, table_name: str, row_id: str):
        for row in self._table(table_name):
            if str(row.get("Id")) == str(row_id):
                return row
        return None

    # --- Documents ---------------------------------------------------------
    def get_company_info(self) -> Dict[str, Any]:
        return {"status": "ok", "output": {"CompanyInfo": self.company_info}}

    def get_company_raw(self) -> Dict[str, Any]:
        return {"status": "ok", "output": self.company_raw}

    def get_bill_payments(self) -> Dict[str, Any]:
        return {"status": "ok", "output": self.bill_payments}

    def get_corporate_expense_ledger(self) -> Dict[str, Any]:
        return {"status": "ok", "output": self.corporate_expense_ledger}

    def get_reimbursement_policy(self) -> Dict[str, Any]:
        return {"status": "ok", "output": self.reimbursement_policy}

    def get_break_even_analysis(self) -> Dict[str, Any]:
        return {"status": "ok", "output": self.break_even_analysis}

    # --- Customers ---------------------------------------------------------
    def get_customer(self, customer_id: str) -> Dict[str, Any]:
        c = self._get("customers", customer_id)
        if c:
            return {"status": "ok", "output": {"Customer": c}}
        return {"status": "failed", "output": f"Customer {customer_id} not found"}

    def create_customer(self, DisplayName: str = "", GivenName: str | None = None,
                        FamilyName: str | None = None, CompanyName: str | None = None,
                        PrimaryEmailAddr: Dict[str, str] | None = None,
                        PrimaryPhone: Dict[str, str] | None = None,
                        BillAddr: Dict[str, str] | None = None,
                        Notes: str | None = None) -> Dict[str, Any]:
        now = self._now()
        new_id = str(self._next_int_id("customers"))
        customer = {
            "Id": new_id,
            "DisplayName": DisplayName or "",
            "GivenName": GivenName,
            "FamilyName": FamilyName,
            "CompanyName": CompanyName,
            "PrimaryEmailAddr": PrimaryEmailAddr,
            "PrimaryPhone": PrimaryPhone,
            "BillAddr": BillAddr,
            "Balance": 0.00,
            "Active": True,
            "Job": False,
            "Notes": Notes,
            "MetaData": {"CreateTime": now, "LastUpdatedTime": now},
            "SyncToken": "0",
        }
        self.customers.append(customer)
        return {"status": "ok", "output": {"Customer": customer}}

    def update_customer(self, customer_id: str, DisplayName: str | None = None,
                        GivenName: str | None = None, FamilyName: str | None = None,
                        CompanyName: str | None = None,
                        PrimaryEmailAddr: Dict[str, str] | None = None,
                        PrimaryPhone: Dict[str, str] | None = None,
                        BillAddr: Dict[str, str] | None = None,
                        Active: bool | None = None, Notes: str | None = None) -> Dict[str, Any]:
        c = self._get("customers", customer_id)
        if not c:
            return {"status": "failed", "output": f"Customer {customer_id} not found"}
        data = {
            "DisplayName": DisplayName, "GivenName": GivenName, "FamilyName": FamilyName,
            "CompanyName": CompanyName, "PrimaryEmailAddr": PrimaryEmailAddr,
            "PrimaryPhone": PrimaryPhone, "BillAddr": BillAddr, "Active": Active, "Notes": Notes,
        }
        updatable = {"DisplayName", "GivenName", "FamilyName", "CompanyName",
                     "PrimaryEmailAddr", "PrimaryPhone", "BillAddr", "Active", "Notes"}
        for k, v in data.items():
            if k in updatable and v is not None:
                c[k] = v
        existing_meta = c.get("MetaData") or {}
        meta = dict(existing_meta) if isinstance(existing_meta, dict) else {}
        meta.setdefault("CreateTime", self._now())
        meta["LastUpdatedTime"] = self._now()
        c["MetaData"] = meta
        try:
            current_sync = int(c.get("SyncToken") or 0)
        except (TypeError, ValueError):
            current_sync = 0
        c["SyncToken"] = str(current_sync + 1)
        return {"status": "ok", "output": {"Customer": c}}

    # --- Vendors -----------------------------------------------------------
    def get_vendor(self, vendor_id: str) -> Dict[str, Any]:
        v = self._get("vendors", vendor_id)
        if v:
            return {"status": "ok", "output": {"Vendor": v}}
        return {"status": "failed", "output": f"Vendor {vendor_id} not found"}

    def create_vendor(self, DisplayName: str = "", CompanyName: str | None = None,
                      PrimaryEmailAddr: Dict[str, str] | None = None,
                      PrimaryPhone: Dict[str, str] | None = None,
                      BillAddr: Dict[str, str] | None = None,
                      AcctNum: str | None = None, Vendor1099: bool = False) -> Dict[str, Any]:
        now = self._now()
        new_id = str(self._next_int_id("vendors"))
        vendor = {
            "Id": new_id,
            "DisplayName": DisplayName or "",
            "CompanyName": CompanyName,
            "PrimaryEmailAddr": PrimaryEmailAddr,
            "PrimaryPhone": PrimaryPhone,
            "BillAddr": BillAddr,
            "Balance": 0.00,
            "Active": True,
            "AcctNum": AcctNum,
            "Vendor1099": Vendor1099,
            "MetaData": {"CreateTime": now, "LastUpdatedTime": now},
            "SyncToken": "0",
        }
        self.vendors.append(vendor)
        return {"status": "ok", "output": {"Vendor": vendor}}

    def update_vendor(self, vendor_id: str, DisplayName: str | None = None,
                      CompanyName: str | None = None,
                      PrimaryEmailAddr: Dict[str, str] | None = None,
                      PrimaryPhone: Dict[str, str] | None = None,
                      BillAddr: Dict[str, str] | None = None, Active: bool | None = None,
                      AcctNum: str | None = None, Vendor1099: bool | None = None) -> Dict[str, Any]:
        v = self._get("vendors", vendor_id)
        if not v:
            return {"status": "failed", "output": f"Vendor {vendor_id} not found"}
        data = {
            "DisplayName": DisplayName, "CompanyName": CompanyName,
            "PrimaryEmailAddr": PrimaryEmailAddr, "PrimaryPhone": PrimaryPhone,
            "BillAddr": BillAddr, "Active": Active, "AcctNum": AcctNum, "Vendor1099": Vendor1099,
        }
        updatable = {"DisplayName", "CompanyName", "PrimaryEmailAddr",
                     "PrimaryPhone", "BillAddr", "Active", "AcctNum", "Vendor1099"}
        for k, val in data.items():
            if k in updatable and val is not None:
                v[k] = val
        existing_meta = v.get("MetaData") or {}
        meta = dict(existing_meta) if isinstance(existing_meta, dict) else {}
        meta.setdefault("CreateTime", self._now())
        meta["LastUpdatedTime"] = self._now()
        v["MetaData"] = meta
        try:
            current_sync = int(v.get("SyncToken") or 0)
        except (TypeError, ValueError):
            current_sync = 0
        v["SyncToken"] = str(current_sync + 1)
        return {"status": "ok", "output": {"Vendor": v}}

    # --- Items -------------------------------------------------------------
    def get_item(self, item_id: str) -> Dict[str, Any]:
        it = self._get("items", item_id)
        if it:
            return {"status": "ok", "output": {"Item": it}}
        return {"status": "failed", "output": f"Item {item_id} not found"}

    def create_item(self, Name: str = "", Description: str | None = None,
                    Type: str = "Service", UnitPrice: float = 0,
                    IncomeAccountRef: Dict[str, str] | None = None,
                    Taxable: bool = False) -> Dict[str, Any]:
        now = self._now()
        new_id = str(self._next_int_id("items"))
        item = {
            "Id": new_id,
            "Name": Name or "",
            "Description": Description,
            "Type": Type or "Service",
            "UnitPrice": float(UnitPrice or 0),
            "IncomeAccountRef": IncomeAccountRef or {"value": "1", "name": "Landscaping Services Revenue"},
            "Active": True,
            "Taxable": Taxable if Taxable is not None else False,
            "MetaData": {"CreateTime": now, "LastUpdatedTime": now},
            "SyncToken": "0",
        }
        self.items.append(item)
        return {"status": "ok", "output": {"Item": item}}

    def update_item(self, item_id: str, Name: str | None = None, Description: str | None = None,
                    UnitPrice: float | None = None, Active: bool | None = None,
                    Taxable: bool | None = None,
                    IncomeAccountRef: Dict[str, str] | None = None) -> Dict[str, Any]:
        it = self._get("items", item_id)
        if not it:
            return {"status": "failed", "output": f"Item {item_id} not found"}
        data = {
            "Name": Name, "Description": Description, "UnitPrice": UnitPrice,
            "Active": Active, "Taxable": Taxable, "IncomeAccountRef": IncomeAccountRef,
        }
        updatable = {"Name", "Description", "UnitPrice", "Active", "Taxable", "IncomeAccountRef"}
        for k, v in data.items():
            if k in updatable and v is not None:
                it[k] = float(v) if k == "UnitPrice" else v
        meta = dict(it["MetaData"]); meta["LastUpdatedTime"] = self._now()
        it["MetaData"] = meta
        it["SyncToken"] = str(int(it["SyncToken"]) + 1)
        return {"status": "ok", "output": {"Item": it}}

    # --- Accounts ----------------------------------------------------------
    def get_account(self, account_id: str) -> Dict[str, Any]:
        a = self._get("accounts", account_id)
        if a:
            return {"status": "ok", "output": {"Account": a}}
        return {"status": "failed", "output": f"Account {account_id} not found"}

    # --- Invoices ----------------------------------------------------------
    def get_invoice(self, invoice_id: str) -> Dict[str, Any]:
        inv = self._get("invoices", invoice_id)
        if inv:
            return {"status": "ok", "output": {"Invoice": inv}}
        return {"status": "failed", "output": f"Invoice {invoice_id} not found"}

    def get_invoice_pdf(self, invoice_id: str) -> Dict[str, Any]:
        inv = self._get("invoices", invoice_id)
        if inv:
            return {"status": "ok", "output": {
                "url": f"https://quickbooks.api.intuit.com/v3/company/{REALM_ID}/invoice/{invoice_id}/pdf"
            }}
        return {"status": "failed", "output": f"Invoice {invoice_id} not found"}

    def create_invoice(self, CustomerRef: Dict[str, str] | None = None,
                       Line: List[Dict[str, Any]] | None = None,
                       TxnDate: str | None = None, DueDate: str | None = None,
                       BillEmail: Dict[str, str] | None = None) -> Dict[str, Any]:
        now = self._now()
        new_id = str(self._next_int_id("invoices"))
        lines = list(Line or [])
        total = sum(l.get("Amount", 0) for l in lines if l.get("DetailType") != "SubTotalLineDetail")
        lines.append({"Amount": total, "DetailType": "SubTotalLineDetail", "SubTotalLineDetail": {}})
        invoice = {
            "Id": new_id,
            "DocNumber": new_id,
            "TxnDate": TxnDate or now[:10],
            "DueDate": DueDate or now[:10],
            "CustomerRef": CustomerRef or {},
            "Line": lines,
            "TotalAmt": total,
            "Balance": total,
            "PrintStatus": "NotSet",
            "EmailStatus": "NotSet",
            "BillEmail": BillEmail,
            "Status": "Open",
            "MetaData": {"CreateTime": now, "LastUpdatedTime": now},
            "SyncToken": "0",
        }
        self.invoices.append(invoice)
        return {"status": "ok", "output": {"Invoice": invoice}}

    def update_invoice(self, invoice_id: str, CustomerRef: Dict[str, str] | None = None,
                       Line: List[Dict[str, Any]] | None = None, DueDate: str | None = None,
                       BillEmail: Dict[str, str] | None = None, PrintStatus: str | None = None,
                       EmailStatus: str | None = None) -> Dict[str, Any]:
        inv = self._get("invoices", invoice_id)
        if not inv:
            return {"status": "failed", "output": f"Invoice {invoice_id} not found"}
        data = {
            "DueDate": DueDate, "CustomerRef": CustomerRef, "Line": Line,
            "BillEmail": BillEmail, "PrintStatus": PrintStatus, "EmailStatus": EmailStatus,
        }
        updatable = {"DueDate", "CustomerRef", "Line", "BillEmail", "PrintStatus", "EmailStatus"}
        for k, v in data.items():
            if k in updatable and v is not None:
                inv[k] = v
        if Line is not None:
            total = sum(l.get("Amount", 0) for l in Line if l.get("DetailType") != "SubTotalLineDetail")
            inv["TotalAmt"] = total
            inv["Balance"] = total
        existing_meta = inv.get("MetaData") or {}
        meta = dict(existing_meta) if isinstance(existing_meta, dict) else {}
        meta.setdefault("CreateTime", self._now())
        meta["LastUpdatedTime"] = self._now()
        inv["MetaData"] = meta
        try:
            current_sync = int(inv.get("SyncToken") or 0)
        except (TypeError, ValueError):
            current_sync = 0
        inv["SyncToken"] = str(current_sync + 1)
        return {"status": "ok", "output": {"Invoice": inv}}

    def void_invoice(self, invoice_id: str) -> Dict[str, Any]:
        inv = self._get("invoices", invoice_id)
        if not inv:
            return {"status": "failed", "output": f"Invoice {invoice_id} not found"}
        existing_meta = inv.get("MetaData") or {}
        meta = dict(existing_meta) if isinstance(existing_meta, dict) else {}
        meta.setdefault("CreateTime", self._now())
        meta["LastUpdatedTime"] = self._now()
        try:
            current_sync = int(inv.get("SyncToken") or 0)
        except (TypeError, ValueError):
            current_sync = 0
        inv["Status"] = "Voided"
        inv["Balance"] = 0.00
        inv["MetaData"] = meta
        inv["SyncToken"] = str(current_sync + 1)
        return {"status": "ok", "output": {"Invoice": inv}}

    def send_invoice(self, invoice_id: str) -> Dict[str, Any]:
        inv = self._get("invoices", invoice_id)
        if not inv:
            return {"status": "failed", "output": f"Invoice {invoice_id} not found"}
        existing_meta = inv.get("MetaData") or {}
        meta = dict(existing_meta) if isinstance(existing_meta, dict) else {}
        meta.setdefault("CreateTime", self._now())
        meta["LastUpdatedTime"] = self._now()
        inv["EmailStatus"] = "Sent"
        inv["MetaData"] = meta
        return {"status": "ok", "output": {"Invoice": inv}}

    # --- Bills -------------------------------------------------------------
    def get_bill(self, bill_id: str) -> Dict[str, Any]:
        b = self._get("bills", bill_id)
        if b:
            return {"status": "ok", "output": {"Bill": b}}
        return {"status": "failed", "output": f"Bill {bill_id} not found"}

    def create_bill(self, VendorRef: Dict[str, str] | None = None,
                    Line: List[Dict[str, Any]] | None = None,
                    TxnDate: str | None = None, DueDate: str | None = None,
                    DocNumber: str | None = None) -> Dict[str, Any]:
        now = self._now()
        new_id = str(self._next_int_id("bills"))
        lines = Line or []
        total = sum(l.get("Amount", 0) for l in lines)
        bill = {
            "Id": new_id,
            "VendorRef": VendorRef or {},
            "TxnDate": TxnDate or now[:10],
            "DueDate": DueDate or now[:10],
            "TotalAmt": total,
            "Balance": total,
            "Line": lines,
            "Status": "Open",
            "DocNumber": DocNumber or f"BILL-{new_id}",
            "MetaData": {"CreateTime": now, "LastUpdatedTime": now},
            "SyncToken": "0",
        }
        self.bills.append(bill)
        return {"status": "ok", "output": {"Bill": bill}}

    def pay_bill(self, bill_id: str) -> Dict[str, Any]:
        b = self._get("bills", bill_id)
        if not b:
            return {"status": "failed", "output": f"Bill {bill_id} not found"}
        existing_meta = b.get("MetaData") or {}
        meta = dict(existing_meta) if isinstance(existing_meta, dict) else {}
        meta.setdefault("CreateTime", self._now())
        meta["LastUpdatedTime"] = self._now()
        try:
            current_sync = int(b.get("SyncToken") or 0)
        except (TypeError, ValueError):
            current_sync = 0
        b["Balance"] = 0.00
        b["Status"] = "Paid"
        b["MetaData"] = meta
        b["SyncToken"] = str(current_sync + 1)
        return {"status": "ok", "output": {"Bill": b}}

    # --- Payments ----------------------------------------------------------
    def get_payment(self, payment_id: str) -> Dict[str, Any]:
        p = self._get("payments", payment_id)
        if p:
            return {"status": "ok", "output": {"Payment": p}}
        return {"status": "failed", "output": f"Payment {payment_id} not found"}

    def create_payment(self, CustomerRef: Dict[str, str] | None = None, TotalAmt: float = 0,
                       Line: List[Dict[str, Any]] | None = None,
                       TxnDate: str | None = None) -> Dict[str, Any]:
        now = self._now()
        new_id = str(self._next_int_id("payments"))
        total = float(TotalAmt or 0)
        payment = {
            "Id": new_id,
            "TxnDate": TxnDate or now[:10],
            "CustomerRef": CustomerRef or {},
            "TotalAmt": total,
            "Line": Line or [],
            "MetaData": {"CreateTime": now, "LastUpdatedTime": now},
            "SyncToken": "0",
        }
        self.payments.append(payment)

        for line in payment.get("Line", []):
            for linked in line.get("LinkedTxn", []):
                if linked.get("TxnType") == "Invoice":
                    inv_id = linked.get("TxnId")
                    inv = self._get("invoices", inv_id)
                    if not inv:
                        continue
                    new_balance = max(0, inv["Balance"] - line.get("Amount", 0))
                    inv["Balance"] = new_balance
                    if new_balance == 0:
                        inv["Status"] = "Paid"

        return {"status": "ok", "output": {"Payment": payment}}

    # --- Estimates ---------------------------------------------------------
    def get_estimate(self, estimate_id: str) -> Dict[str, Any]:
        e = self._get("estimates", estimate_id)
        if e:
            return {"status": "ok", "output": {"Estimate": e}}
        return {"status": "failed", "output": f"Estimate {estimate_id} not found"}

    def create_estimate(self, CustomerRef: Dict[str, str] | None = None,
                        Line: List[Dict[str, Any]] | None = None,
                        TxnDate: str | None = None, ExpirationDate: str | None = None) -> Dict[str, Any]:
        now = self._now()
        new_id = str(self._next_int_id("estimates"))
        lines = Line or []
        total = sum(l.get("Amount", 0) for l in lines)
        estimate = {
            "Id": new_id,
            "DocNumber": f"E-{new_id}",
            "TxnDate": TxnDate or now[:10],
            "ExpirationDate": ExpirationDate,
            "CustomerRef": CustomerRef or {},
            "Line": lines,
            "TotalAmt": total,
            "TxnStatus": "Pending",
            "AcceptedDate": None,
            "LinkedTxn": [],
            "MetaData": {"CreateTime": now, "LastUpdatedTime": now},
            "SyncToken": "0",
        }
        self.estimates.append(estimate)
        return {"status": "ok", "output": {"Estimate": estimate}}

    def convert_estimate_to_invoice(self, estimate_id: str) -> Dict[str, Any]:
        e = self._get("estimates", estimate_id)
        if not e:
            return {"status": "failed", "output": f"Estimate {estimate_id} not found"}
        if e["TxnStatus"] not in ("Pending", "Accepted"):
            return {"status": "failed",
                    "output": f"Estimate {estimate_id} cannot be converted (status: {e['TxnStatus']})"}

        now = self._now()
        lines = [l for l in e["Line"] if l.get("DetailType") == "SalesItemLineDetail"]
        total = sum(l.get("Amount", 0) for l in lines)
        lines.append({"Amount": total, "DetailType": "SubTotalLineDetail", "SubTotalLineDetail": {}})

        new_inv_id = str(self._next_int_id("invoices"))
        invoice = {
            "Id": new_inv_id,
            "DocNumber": new_inv_id,
            "TxnDate": now[:10],
            "DueDate": now[:10],
            "CustomerRef": e["CustomerRef"],
            "Line": lines,
            "TotalAmt": total,
            "Balance": total,
            "PrintStatus": "NotSet",
            "EmailStatus": "NotSet",
            "BillEmail": None,
            "Status": "Open",
            "MetaData": {"CreateTime": now, "LastUpdatedTime": now},
            "SyncToken": "0",
        }
        self.invoices.append(invoice)

        meta = dict(e["MetaData"]); meta["LastUpdatedTime"] = now
        e["TxnStatus"] = "Accepted"
        e["AcceptedDate"] = now[:10]
        e["LinkedTxn"] = [{"TxnId": new_inv_id, "TxnType": "Invoice"}]
        e["MetaData"] = meta
        e["SyncToken"] = str(int(e["SyncToken"]) + 1)

        return {"status": "ok", "output": {"Invoice": invoice}}

    # --- Expenses (Purchases) ----------------------------------------------
    def get_expense(self, expense_id: str) -> Dict[str, Any]:
        e = self._get("expenses", expense_id)
        if e:
            return {"status": "ok", "output": {"Purchase": e}}
        return {"status": "failed", "output": f"Expense {expense_id} not found"}

    def create_expense(self, AccountRef: Dict[str, str] | None = None,
                       Line: List[Dict[str, Any]] | None = None,
                       PaymentType: str = "CreditCard", TxnDate: str | None = None) -> Dict[str, Any]:
        now = self._now()
        new_id = str(self._next_int_id("expenses"))
        lines = Line or []
        total = sum(l.get("Amount", 0) for l in lines)
        expense = {
            "Id": new_id,
            "TxnDate": TxnDate or now[:10],
            "AccountRef": AccountRef or {},
            "PaymentType": PaymentType or "CreditCard",
            "TotalAmt": total,
            "Line": lines,
            "MetaData": {"CreateTime": now, "LastUpdatedTime": now},
            "SyncToken": "0",
        }
        self.expenses.append(expense)
        return {"status": "ok", "output": {"Purchase": expense}}

    # --- Query -------------------------------------------------------------
    def execute_query(self, query: str) -> Dict[str, Any]:
        query_str = query.strip()

        parts = query_str.upper().split()
        if len(parts) < 4 or parts[0] != "SELECT" or parts[2] != "FROM":
            return {"status": "failed", "output": f"Invalid query syntax: {query_str}"}

        entity = query_str.split("FROM")[1].strip().split()[0].strip()

        entity_map = {
            "Invoice": "invoices",
            "Customer": "customers",
            "Vendor": "vendors",
            "Item": "items",
            "Account": "accounts",
            "Bill": "bills",
            "Payment": "payments",
            "Estimate": "estimates",
            "Purchase": "expenses",
        }

        if entity not in entity_map:
            return {"status": "failed", "output": f"Unknown entity: {entity}"}

        results = list(self._table(entity_map[entity]))

        upper_query = query_str.upper()
        if "WHERE" in upper_query:
            where_idx = upper_query.index("WHERE") + 5
            where_clause = query_str[where_idx:].strip()
            results = self._apply_where(results, where_clause)

        return {"status": "ok", "output": {
            "QueryResponse": {
                entity: results,
                "startPosition": 1,
                "maxResults": len(results),
                "totalCount": len(results),
            }
        }}

    def _apply_where(self, results, where_clause):
        conditions = re.split(r'\s+AND\s+', where_clause, flags=re.IGNORECASE)
        for cond in conditions:
            cond = cond.strip()
            match = re.match(r"(\w+)\s*(=|!=|>|<|>=|<=|LIKE)\s*'?([^']*)'?", cond, re.IGNORECASE)
            if not match:
                continue
            field = match.group(1)
            op = match.group(2).upper()
            value = match.group(3)
            filtered = []
            for item in results:
                item_val = self._get_nested_field(item, field)
                if item_val is None:
                    continue
                if self._compare(item_val, op, value):
                    filtered.append(item)
            results = filtered
        return results

    def _get_nested_field(self, item, field):
        if field in item:
            return item[field]
        if field + "Ref" in item:
            ref = item[field + "Ref"]
            if isinstance(ref, dict):
                return ref.get("value")
        parts = field.split(".")
        current = item
        for p in parts:
            if isinstance(current, dict) and p in current:
                current = current[p]
            else:
                return None
        return current

    def _compare(self, item_val, op, value):
        if isinstance(item_val, bool):
            bool_val = value.lower() in ("true", "1", "yes")
            if op == "=":
                return item_val == bool_val
            elif op == "!=":
                return item_val != bool_val
            return False
        try:
            num_item = float(item_val) if not isinstance(item_val, (int, float)) else item_val
            num_val = float(value)
            if op == "=":
                return num_item == num_val
            elif op == "!=":
                return num_item != num_val
            elif op == ">":
                return num_item > num_val
            elif op == "<":
                return num_item < num_val
            elif op == ">=":
                return num_item >= num_val
            elif op == "<=":
                return num_item <= num_val
        except (ValueError, TypeError):
            pass
        str_item = str(item_val)
        if op == "=":
            return str_item.lower() == value.lower()
        elif op == "!=":
            return str_item.lower() != value.lower()
        elif op == "LIKE":
            pattern = value.replace("%", ".*")
            return bool(re.match(pattern, str_item, re.IGNORECASE))
        return False

    # --- Reports -----------------------------------------------------------
    def profit_and_loss(self, start_date: str | None = None, end_date: str | None = None) -> Dict[str, Any]:
        revenue_invoices = list(self.invoices)
        expense_bills = list(self.bills)
        expense_purchases = list(self.expenses)

        if start_date:
            revenue_invoices = [inv for inv in revenue_invoices if (inv.get("TxnDate") or "") >= start_date]
            expense_bills = [b for b in expense_bills if (b.get("TxnDate") or "") >= start_date]
            expense_purchases = [e for e in expense_purchases if (e.get("TxnDate") or "") >= start_date]
        if end_date:
            revenue_invoices = [inv for inv in revenue_invoices if (inv.get("TxnDate") or "") <= end_date]
            expense_bills = [b for b in expense_bills if (b.get("TxnDate") or "") <= end_date]
            expense_purchases = [e for e in expense_purchases if (e.get("TxnDate") or "") <= end_date]

        paid_invoices = [inv for inv in revenue_invoices if inv.get("Status") == "Paid"]
        total_revenue = sum(inv.get("TotalAmt", 0) for inv in paid_invoices)
        total_bill_expenses = sum(b.get("TotalAmt", 0) for b in expense_bills)
        total_purchase_expenses = sum(e.get("TotalAmt", 0) for e in expense_purchases)
        total_expenses = total_bill_expenses + total_purchase_expenses
        net_income = total_revenue - total_expenses

        return {"status": "ok", "output": {
            "Header": {
                "ReportName": "ProfitAndLoss",
                "StartPeriod": start_date or "2025-01-01",
                "EndPeriod": end_date or "2025-12-31",
                "Currency": "USD",
                "Option": [{"Name": "AccountingMethod", "Value": "Accrual"}],
            },
            "Rows": {
                "Row": [
                    {"group": "Income", "Summary": {"ColData": [{"value": "Total Income"}, {"value": f"{total_revenue:.2f}"}]},
                     "Rows": {"Row": [{"ColData": [{"value": "Landscaping Services Revenue"}, {"value": f"{total_revenue:.2f}"}]}]}},
                    {"group": "Expenses", "Summary": {"ColData": [{"value": "Total Expenses"}, {"value": f"{total_expenses:.2f}"}]},
                     "Rows": {"Row": self._build_expense_rows(expense_bills, expense_purchases)}},
                    {"group": "NetIncome", "Summary": {"ColData": [{"value": "Net Income"}, {"value": f"{net_income:.2f}"}]}},
                ]
            },
        }}

    def _build_expense_rows(self, bills, purchases):
        account_totals = {}
        for b in bills:
            for line in b.get("Line", []):
                detail = line.get("AccountBasedExpenseLineDetail", {})
                acct = detail.get("AccountRef", {}).get("name", "Other Expense")
                account_totals[acct] = account_totals.get(acct, 0) + line.get("Amount", 0)
        for p in purchases:
            for line in p.get("Line", []):
                detail = line.get("AccountBasedExpenseLineDetail", {})
                acct = detail.get("AccountRef", {}).get("name", "Other Expense")
                account_totals[acct] = account_totals.get(acct, 0) + line.get("Amount", 0)
        rows = []
        for acct_name, total in sorted(account_totals.items()):
            rows.append({"ColData": [{"value": acct_name}, {"value": f"{total:.2f}"}]})
        return rows

    def balance_sheet(self, start_date: str | None = None, end_date: str | None = None) -> Dict[str, Any]:
        invoices = list(self.invoices)
        bills = list(self.bills)
        total_ar = sum(inv.get("Balance", 0) for inv in invoices if inv.get("Status") not in ("Voided",))
        total_ap = sum(b.get("Balance", 0) for b in bills)

        checking = 47250.00
        savings = 15000.00
        total_assets = checking + savings + total_ar
        total_liabilities = total_ap
        equity = total_assets - total_liabilities

        return {"status": "ok", "output": {
            "Header": {
                "ReportName": "BalanceSheet",
                "StartPeriod": start_date or "2025-01-01",
                "EndPeriod": end_date or "2025-12-31",
                "Currency": "USD",
            },
            "Rows": {
                "Row": [
                    {"group": "Assets", "Summary": {"ColData": [{"value": "Total Assets"}, {"value": f"{total_assets:.2f}"}]},
                     "Rows": {"Row": [
                         {"ColData": [{"value": "Business Checking"}, {"value": f"{checking:.2f}"}]},
                         {"ColData": [{"value": "Business Savings"}, {"value": f"{savings:.2f}"}]},
                         {"ColData": [{"value": "Accounts Receivable"}, {"value": f"{total_ar:.2f}"}]},
                     ]}},
                    {"group": "Liabilities", "Summary": {"ColData": [{"value": "Total Liabilities"}, {"value": f"{total_liabilities:.2f}"}]},
                     "Rows": {"Row": [
                         {"ColData": [{"value": "Accounts Payable"}, {"value": f"{total_ap:.2f}"}]},
                     ]}},
                    {"group": "Equity", "Summary": {"ColData": [{"value": "Total Equity"}, {"value": f"{equity:.2f}"}]}},
                ]
            },
        }}

    def accounts_receivable_aging(self) -> Dict[str, Any]:
        aging_buckets = {"Current": [], "1-30": [], "31-60": [], "61-90": [], "91+": []}
        today = datetime.utcnow().strftime("%Y-%m-%d")

        for inv in self.invoices:
            if inv.get("Balance", 0) <= 0 or inv.get("Status") == "Voided":
                continue
            due_date = inv.get("DueDate", today)
            days_overdue = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(due_date, "%Y-%m-%d")).days
            if days_overdue <= 0:
                aging_buckets["Current"].append(inv)
            elif days_overdue <= 30:
                aging_buckets["1-30"].append(inv)
            elif days_overdue <= 60:
                aging_buckets["31-60"].append(inv)
            elif days_overdue <= 90:
                aging_buckets["61-90"].append(inv)
            else:
                aging_buckets["91+"].append(inv)

        rows = []
        for bucket, invoices in aging_buckets.items():
            total = sum(inv.get("Balance", 0) for inv in invoices)
            rows.append({
                "ColData": [{"value": bucket}, {"value": f"{total:.2f}"}],
                "Details": [{"CustomerRef": inv.get("CustomerRef"), "Balance": inv.get("Balance"), "DueDate": inv.get("DueDate")} for inv in invoices],
            })

        return {"status": "ok", "output": {
            "Header": {
                "ReportName": "AgedReceivableDetail",
                "ReportBasis": "Accrual",
                "Currency": "USD",
            },
            "Rows": {"Row": rows},
        }}

    def accounts_payable_aging(self) -> Dict[str, Any]:
        aging_buckets = {"Current": [], "1-30": [], "31-60": [], "61-90": [], "91+": []}
        today = datetime.utcnow().strftime("%Y-%m-%d")

        for bill in self.bills:
            if bill.get("Balance", 0) <= 0:
                continue
            due_date = bill.get("DueDate", today)
            days_overdue = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(due_date, "%Y-%m-%d")).days
            if days_overdue <= 0:
                aging_buckets["Current"].append(bill)
            elif days_overdue <= 30:
                aging_buckets["1-30"].append(bill)
            elif days_overdue <= 60:
                aging_buckets["31-60"].append(bill)
            elif days_overdue <= 90:
                aging_buckets["61-90"].append(bill)
            else:
                aging_buckets["91+"].append(bill)

        rows = []
        for bucket, bills in aging_buckets.items():
            total = sum(b.get("Balance", 0) for b in bills)
            rows.append({
                "ColData": [{"value": bucket}, {"value": f"{total:.2f}"}],
                "Details": [{"VendorRef": b.get("VendorRef"), "Balance": b.get("Balance"), "DueDate": b.get("DueDate")} for b in bills],
            })

        return {"status": "ok", "output": {
            "Header": {
                "ReportName": "AgedPayableDetail",
                "ReportBasis": "Accrual",
                "Currency": "USD",
            },
            "Rows": {"Row": rows},
        }}


if __name__ == "__main__":
    s = QuickbooksSession(seed=12)
    print(s.get_company_info())
    print(s.get_customer("1"))
    print(s.execute_query("SELECT * FROM Invoice"))
