import random
from typing import Dict, List, Any
from pathlib import Path
import yaml
import sys
from datetime import datetime, timezone

WORK_DIR = Path('.').__str__()
if WORK_DIR not in sys.path:
    sys.path.append(WORK_DIR)

from software.utils.core import OSConnector, DummyOSConnector
from software.utils.world_snapshot import restore_into, seed_mode, resolve_seed
from software.utils.time import TimeMachine

CORPUS_PATH = Path(__file__).resolve().parent / "corpus"


def _to_bool(v) -> bool:
    return str(v).strip().lower() == "true"


def _opt_int(v, default=0):
    if v is None or v == "":
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _opt_str(v, default=""):
    if v is None:
        return default
    return str(v)


class StripeSession:
    """Deterministic sandbox for the Stripe mock, ported from the FastAPI service.

    Amounts are integer cents. State is loaded from the corpus at init; subsequent
    calls read and mutate the in-memory tables so repeated calls stay consistent.
    """

    def __init__(self, os_cfg, seed=None):
        # Seedless: world loaded verbatim from a frozen snapshot next to
        # this module; `seed` is accepted for client compat and ignored.
        if seed_mode():
            # Seed architecture: world rolled from a seed (re-armed).
            self.rng = random.Random(resolve_seed(seed))
            self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()
            self.time_machine = TimeMachine(rng=self.rng)

            with open(CORPUS_PATH / "stripe.yaml") as f:
                info = yaml.safe_load(f)

            self.customers: List[Dict[str, Any]] = [
                {
                    **r,
                    "object": "customer",
                    "delinquent": _to_bool(r.get("delinquent")),
                    "balance": _opt_int(r.get("balance"), 0),
                    "created": _opt_int(r.get("created"), 0),
                }
                for r in info.get("customers", [])
            ]
            self.products: List[Dict[str, Any]] = [
                {**r, "object": "product", "active": _to_bool(r.get("active")),
                 "created": _opt_int(r.get("created"), 0)}
                for r in info.get("products", [])
            ]
            self.prices: List[Dict[str, Any]] = []
            for r in info.get("prices", []):
                recurring = {"interval": r["recurring_interval"]} if r["recurring_interval"] else None
                self.prices.append({
                    **r,
                    "object": "price",
                    "unit_amount": _opt_int(r.get("unit_amount"), 0),
                    "active": _to_bool(r.get("active")),
                    "recurring": recurring,
                    "type": "recurring" if recurring else "one_time",
                })
            self.charges: List[Dict[str, Any]] = [
                {**r, "object": "charge", "amount": _opt_int(r.get("amount"), 0),
                 "paid": _to_bool(r.get("paid")), "refunded": _to_bool(r.get("refunded")),
                 "amount_refunded": _opt_int(r.get("amount_refunded"), 0),
                 "created": _opt_int(r.get("created"), 0)}
                for r in info.get("charges", [])
            ]
            self.invoices: List[Dict[str, Any]] = [
                {
                    **r,
                    "object": "invoice",
                    "subscription": _opt_str(r.get("subscription"), "") or None,
                    "charge": _opt_str(r.get("charge"), "") or None,
                    "amount_due": _opt_int(r.get("amount_due"), 0),
                    "amount_paid": _opt_int(r.get("amount_paid"), 0),
                    "created": _opt_int(r.get("created"), 0),
                    "due_date": _opt_int(r.get("due_date"), None),
                }
                for r in info.get("invoices", [])
            ]
            self.subscriptions: List[Dict[str, Any]] = [
                {**r, "object": "subscription", "quantity": _opt_int(r.get("quantity"), 0),
                 "current_period_start": _opt_int(r.get("current_period_start"), 0),
                 "current_period_end": _opt_int(r.get("current_period_end"), 0),
                 "cancel_at_period_end": _to_bool(r.get("cancel_at_period_end")),
                 "created": _opt_int(r.get("created"), 0)}
                for r in info.get("subscriptions", [])
            ]
            self.balance: Dict[str, Any] = dict(info.get("balance", {}))
            self.payment_intents: List[Dict[str, Any]] = []
            self.refunds: List[Dict[str, Any]] = []

            from software.utils.world_data import hydrate as _hydrate_world_data
            _hydrate_world_data(self, "LightStripe")
        else:
            # Seedless: world loaded verbatim from the frozen snapshot.
            restore_into(self, Path(__file__).resolve().parent / "world.pkl")
            self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()

    def get_session_dict(self):
        return {"charges": self.charges}

    # --- helpers -----------------------------------------------------------
    def _now(self) -> int:
        try:
            return int(datetime.strptime(self.os.now(), "%Y-%m-%d %H:%M:%S")
                       .replace(tzinfo=timezone.utc).timestamp())
        except (ValueError, TypeError):
            return 0

    def uuid(self) -> str:
        alphabet = "0123456789abcdef"
        return ''.join(self.rng.choices(alphabet, k=16))

    def _new_id(self, prefix) -> str:
        return f"{prefix}_{self.uuid()}"

    def _list_envelope(self, data, url):
        return {"object": "list", "url": url, "has_more": False, "data": data}

    def _find(self, store, obj_id):
        return next((x for x in store if x["id"] == obj_id), None)

    def _record_charge(self, amount, currency, customer, description, payment_intent, status):
        charge = {
            "id": self._new_id("ch"),
            "object": "charge",
            "customer": customer,
            "amount": int(amount),
            "currency": currency or "usd",
            "status": status,
            "paid": status == "succeeded",
            "refunded": False,
            "amount_refunded": 0,
            "description": description or "",
            "payment_intent": payment_intent,
            "created": self._now(),
        }
        self.charges.append(charge)
        return charge

    # --- Customers ---------------------------------------------------------
    def list_customers(self, limit: int = 10, email: str | None = None) -> Dict[str, Any]:
        results = list(self.customers)
        if email:
            results = [c for c in results if c["email"] == email]
        return {"status": "ok", "output": self._list_envelope(results[:limit], "/v1/customers")}

    def get_customer(self, customer_id: str) -> Dict[str, Any]:
        c = self._find(self.customers, customer_id)
        if not c:
            return {"status": "failed", "output": f"No such customer: {customer_id}"}
        return {"status": "ok", "output": c}

    def create_customer(self, name: str | None = None, email: str | None = None,
                        description: str | None = None, currency: str = "usd",
                        phone: str | None = None) -> Dict[str, Any]:
        customer = {
            "id": self._new_id("cus"),
            "object": "customer",
            "name": name or "",
            "email": email or "",
            "description": description or "",
            "currency": currency or "usd",
            "delinquent": False,
            "balance": 0,
            "phone": phone or "",
            "created": self._now(),
        }
        self.customers.append(customer)
        return {"status": "ok", "output": customer}

    # --- Products / Prices -------------------------------------------------
    def list_products(self, limit: int = 10) -> Dict[str, Any]:
        return {"status": "ok", "output": self._list_envelope(list(self.products)[:limit], "/v1/products")}

    def list_prices(self, limit: int = 10, product: str | None = None) -> Dict[str, Any]:
        results = list(self.prices)
        if product:
            results = [p for p in results if p["product"] == product]
        return {"status": "ok", "output": self._list_envelope(results[:limit], "/v1/prices")}

    # --- Payment Intents / Charges / Refunds -------------------------------
    def create_payment_intent(self, amount: int, currency: str = "usd", customer: str | None = None,
                              description: str | None = None, confirm: bool = False) -> Dict[str, Any]:
        if amount is None or amount <= 0:
            return {"status": "failed", "output": "amount must be a positive integer (cents)"}
        if customer and not self._find(self.customers, customer):
            return {"status": "failed", "output": f"No such customer: {customer}"}
        pi = {
            "id": self._new_id("pi"),
            "object": "payment_intent",
            "amount": int(amount),
            "currency": currency or "usd",
            "customer": customer,
            "description": description or "",
            "status": "succeeded" if confirm else "requires_confirmation",
            "latest_charge": None,
            "created": self._now(),
        }
        if confirm:
            charge = self._record_charge(amount, currency, customer, description, pi["id"], "succeeded")
            pi["latest_charge"] = charge["id"]
        self.payment_intents.append(pi)
        return {"status": "ok", "output": pi}

    def get_payment_intent(self, pi_id: str) -> Dict[str, Any]:
        pi = self._find(self.payment_intents, pi_id)
        if not pi:
            return {"status": "failed", "output": f"No such payment_intent: {pi_id}"}
        return {"status": "ok", "output": pi}

    def list_charges(self, limit: int = 10, customer: str | None = None) -> Dict[str, Any]:
        results = list(self.charges)
        if customer:
            results = [c for c in results if c["customer"] == customer]
        return {"status": "ok", "output": self._list_envelope(results[:limit], "/v1/charges")}

    def get_charge(self, charge_id: str) -> Dict[str, Any]:
        c = self._find(self.charges, charge_id)
        if not c:
            return {"status": "failed", "output": f"No such charge: {charge_id}"}
        return {"status": "ok", "output": c}

    def create_charge(self, amount: int, currency: str = "usd", customer: str | None = None,
                      description: str | None = None) -> Dict[str, Any]:
        if amount is None or amount <= 0:
            return {"status": "failed", "output": "amount must be a positive integer (cents)"}
        if customer and not self._find(self.customers, customer):
            return {"status": "failed", "output": f"No such customer: {customer}"}
        return {"status": "ok", "output": self._record_charge(amount, currency, customer, description, None, "succeeded")}

    def create_refund(self, charge: str, amount: int | None = None,
                      reason: str | None = None) -> Dict[str, Any]:
        if not charge:
            return {"status": "failed", "output": "charge is required"}
        ch = self._find(self.charges, charge)
        if not ch:
            return {"status": "failed", "output": f"No such charge: {charge}"}
        refundable = ch["amount"] - ch["amount_refunded"]
        refund_amount = int(amount) if amount is not None else refundable
        if refund_amount <= 0 or refund_amount > refundable:
            return {"status": "failed", "output": f"Refund amount {refund_amount} exceeds refundable {refundable}"}
        refund = {
            "id": self._new_id("re"),
            "object": "refund",
            "charge": charge,
            "amount": refund_amount,
            "currency": ch["currency"],
            "reason": reason or "requested_by_customer",
            "status": "succeeded",
            "created": self._now(),
        }
        ch["amount_refunded"] += refund_amount
        ch["refunded"] = ch["amount_refunded"] >= ch["amount"]
        self.refunds.append(refund)
        return {"status": "ok", "output": refund}

    # --- Invoices ----------------------------------------------------------
    def list_invoices(self, limit: int = 10, customer: str | None = None,
                      status: str | None = None) -> Dict[str, Any]:
        results = list(self.invoices)
        if customer:
            results = [i for i in results if i["customer"] == customer]
        if status:
            results = [i for i in results if i["status"] == status]
        return {"status": "ok", "output": self._list_envelope(results[:limit], "/v1/invoices")}

    def get_invoice(self, invoice_id: str) -> Dict[str, Any]:
        inv = self._find(self.invoices, invoice_id)
        if not inv:
            return {"status": "failed", "output": f"No such invoice: {invoice_id}"}
        return {"status": "ok", "output": inv}

    def create_invoice(self, customer: str, amount_due: int = 0, currency: str = "usd",
                       subscription: str | None = None) -> Dict[str, Any]:
        if not customer or not self._find(self.customers, customer):
            return {"status": "failed", "output": f"No such customer: {customer}"}
        seq = len(self.invoices) + 1
        invoice = {
            "id": self._new_id("in"),
            "object": "invoice",
            "customer": customer,
            "subscription": subscription,
            "amount_due": int(amount_due) if amount_due is not None else 0,
            "amount_paid": 0,
            "currency": currency or "usd",
            "status": "draft",
            "number": f"ORBIT-{seq:04d}",
            "charge": None,
            "created": self._now(),
            "due_date": None,
        }
        self.invoices.append(invoice)
        return {"status": "ok", "output": invoice}

    # --- Subscriptions -----------------------------------------------------
    def list_subscriptions(self, limit: int = 10, customer: str | None = None,
                           status: str | None = None) -> Dict[str, Any]:
        results = list(self.subscriptions)
        if customer:
            results = [s for s in results if s["customer"] == customer]
        if status:
            results = [s for s in results if s["status"] == status]
        return {"status": "ok", "output": self._list_envelope(results[:limit], "/v1/subscriptions")}

    def get_subscription(self, sub_id: str) -> Dict[str, Any]:
        s = self._find(self.subscriptions, sub_id)
        if not s:
            return {"status": "failed", "output": f"No such subscription: {sub_id}"}
        return {"status": "ok", "output": s}

    def create_subscription(self, customer: str, price: str, quantity: int = 1) -> Dict[str, Any]:
        if not customer or not self._find(self.customers, customer):
            return {"status": "failed", "output": f"No such customer: {customer}"}
        if not price or not self._find(self.prices, price):
            return {"status": "failed", "output": f"No such price: {price}"}
        now = self._now()
        sub = {
            "id": self._new_id("sub"),
            "object": "subscription",
            "customer": customer,
            "price": price,
            "status": "active",
            "quantity": int(quantity or 1),
            "current_period_start": now,
            "current_period_end": now + 2592000,
            "cancel_at_period_end": False,
            "created": now,
        }
        self.subscriptions.append(sub)
        return {"status": "ok", "output": sub}

    # --- Balance -----------------------------------------------------------
    def get_balance(self) -> Dict[str, Any]:
        return {"status": "ok", "output": self.balance}


if __name__ == "__main__":
    s = StripeSession(seed=12)
    print(s.list_customers())
    print(s.get_balance())
