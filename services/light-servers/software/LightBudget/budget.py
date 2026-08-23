from typing import Dict, List, Optional
from pathlib import Path
import random
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta

WORK_DIR = Path('.').__str__()
if WORK_DIR not in sys.path:
    sys.path.append(WORK_DIR)

from software.utils.core import OSConnector, DummyOSConnector
from software.utils.world_snapshot import restore_into, seed_mode, resolve_seed


TX_KINDS = ("expense", "income")

DEFAULT_CATEGORIES = [
    {"catid": "cat_food",          "name": "Food",          "color": "#FF7043", "monthly_limit": 600.0},
    {"catid": "cat_rent",          "name": "Rent",          "color": "#5C6BC0", "monthly_limit": 1800.0},
    {"catid": "cat_transport",     "name": "Transport",     "color": "#26A69A", "monthly_limit": 300.0},
    {"catid": "cat_entertainment", "name": "Entertainment", "color": "#AB47BC", "monthly_limit": 250.0},
    {"catid": "cat_salary",        "name": "Salary",        "color": "#66BB6A", "monthly_limit": 0.0},
]

SEED_TRANSACTIONS = [
    ("cat_salary",        4500.0, "USD",  1, "Monthly salary",           "income"),
    ("cat_rent",          1800.0, "USD",  2, "January rent",             "expense"),
    ("cat_food",            85.20, "USD", 3, "Groceries at MegaMart",    "expense"),
    ("cat_transport",       55.00, "USD", 4, "Subway pass",              "expense"),
    ("cat_entertainment",   42.00, "USD", 6, "Cinema tickets",           "expense"),
    ("cat_food",            32.50, "USD", 8, "Dinner takeout",           "expense"),
    ("cat_transport",       25.75, "USD", 9, "Ride share",               "expense"),
    ("cat_food",           120.10, "USD", 11, "Weekly groceries",        "expense"),
    ("cat_entertainment",   14.99, "USD", 12, "Streaming subscription",  "expense"),
    ("cat_food",            18.40, "USD", 15, "Coffee shop",             "expense"),
    ("cat_salary",         250.00, "USD", 18, "Freelance payout",        "income"),
    ("cat_transport",       48.00, "USD", 22, "Fuel",                    "expense"),
]


@dataclass
class Category:
    catid: str
    name: str
    color: str
    monthly_limit: float


@dataclass
class Transaction:
    txid: str
    category_id: str
    amount: float
    currency: str
    date: str
    description: str
    kind: str


@dataclass
class Budget:
    bid: str
    month: str
    category_id: str
    limit: float
    spent: float


class BudgetSession:
    def __init__(self, os_cfg, seed=None, fixture=None):
        # Seedless: world loaded verbatim from a frozen snapshot next to
        # this module; `seed` is accepted for client compat and ignored.
        if seed_mode():
            # Seed architecture: world rolled from a seed (re-armed).
            self.rng = random.Random(resolve_seed(seed))
            self.os = OSConnector(
                session_id=os_cfg["session_id"],
                url=os_cfg["url"],
            ) if os_cfg else DummyOSConnector()
            self._today = datetime(2026, 1, 5)
            # Annotations drive the coercion in load_typed_state (categories/
            # transactions/budgets -> their dataclasses via _SHAPES).
            self.categories: Dict[str, Category] = {}
            self.transactions: Dict[str, Transaction] = {}
            self.budgets: Dict[str, Budget] = {}
            # World data loaded verbatim from corpus/state.json (no cooking):
            # dicts rebuilt into Category/Transaction/Budget; "today" -> _today.
            from software.utils.world_data import load_typed_state as _load_typed_state
            _load_typed_state(self, "LightBudget")
            # Task-specific overlay still applies on top for fixture tasks.
            from software.utils.fixtures import apply as _apply_fixtures
            _apply_fixtures(self, "LightBudget", fixture)
        else:
            # Seedless: world loaded verbatim from the frozen snapshot.
            restore_into(self, Path(__file__).resolve().parent / "world.pkl")
            self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()

    def uuid(self) -> str:
        alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        return "".join(self.rng.choices(alphabet, k=22))

    def _month_of(self, iso_date: str) -> str:
        return iso_date[:7]

    def _seed_transactions(self) -> None:
        base = datetime(2026, 1, 1)
        for cat, amount, currency, day, desc, kind in SEED_TRANSACTIONS:
            d = (base + timedelta(days=day - 1)).date().isoformat()
            t = Transaction(
                txid=self.uuid(),
                category_id=cat,
                amount=amount,
                currency=currency,
                date=d,
                description=desc,
                kind=kind,
            )
            self.transactions[t.txid] = t

    def _seed_budgets(self) -> None:
        month = "2026-01"
        spent_by_cat: Dict[str, float] = {}
        for t in self.transactions.values():
            if t.kind == "expense" and self._month_of(t.date) == month:
                spent_by_cat[t.category_id] = spent_by_cat.get(t.category_id, 0.0) + t.amount
        for cat in self.categories.values():
            b = Budget(
                bid=self.uuid(),
                month=month,
                category_id=cat.catid,
                limit=cat.monthly_limit,
                spent=round(spent_by_cat.get(cat.catid, 0.0), 2),
            )
            self.budgets[b.bid] = b

    def get_session_dict(self) -> Dict:
        return {
            "today": self._today.date().isoformat(),
            "categories": {cid: asdict(c) for cid, c in self.categories.items()},
            "transactions": {tid: asdict(t) for tid, t in self.transactions.items()},
            "budgets": {bid: asdict(b) for bid, b in self.budgets.items()},
        }

    def _tx_summary(self, t: Transaction) -> Dict:
        return {
            "txid": t.txid,
            "category_id": t.category_id,
            "amount": t.amount,
            "currency": t.currency,
            "date": t.date,
            "description": t.description,
            "kind": t.kind,
        }

    def _recompute_budget_spent(self, month: str, category_id: Optional[str] = None) -> None:
        for b in self.budgets.values():
            if b.month != month:
                continue
            if category_id is not None and b.category_id != category_id:
                continue
            total = 0.0
            for t in self.transactions.values():
                if t.kind == "expense" and self._month_of(t.date) == month and t.category_id == b.category_id:
                    total += t.amount
            b.spent = round(total, 2)

    def list_categories(self) -> Dict:
        return {"status": "ok", "output": [asdict(c) for c in self.categories.values()]}

    def create_category(self, name: str, color: str = "#888888", monthly_limit: float = 0.0) -> Dict:
        catid = "cat_" + self.uuid()[:8]
        c = Category(catid=catid, name=name, color=color, monthly_limit=float(monthly_limit))
        self.categories[catid] = c
        return {"status": "ok", "output": asdict(c)}

    def delete_category(self, catid: str) -> Dict:
        if catid not in self.categories:
            return {"status": "failed", "output": f"category {catid} not found"}
        del self.categories[catid]
        removed_tx = [tid for tid, t in self.transactions.items() if t.category_id == catid]
        for tid in removed_tx:
            del self.transactions[tid]
        removed_bud = [bid for bid, b in self.budgets.items() if b.category_id == catid]
        for bid in removed_bud:
            del self.budgets[bid]
        return {"status": "ok", "output": {"catid": catid, "removed_transactions": len(removed_tx), "removed_budgets": len(removed_bud)}}

    def update_category(self, catid: str,
                        name: Optional[str] = None,
                        color: Optional[str] = None,
                        monthly_limit: Optional[float] = None) -> Dict:
        c = self.categories.get(catid)
        if not c:
            return {"status": "failed", "output": f"category {catid} not found"}
        if name is not None:
            c.name = name
        if color is not None:
            c.color = color
        if monthly_limit is not None:
            c.monthly_limit = float(monthly_limit)
        return {"status": "ok", "output": asdict(c)}

    def list_transactions(self, category_id: Optional[str] = None,
                          kind: Optional[str] = None,
                          start_date: Optional[str] = None,
                          end_date: Optional[str] = None) -> Dict:
        items = list(self.transactions.values())
        if category_id:
            items = [t for t in items if t.category_id == category_id]
        if kind:
            if kind not in TX_KINDS:
                return {"status": "failed", "output": f"kind must be one of {TX_KINDS}"}
            items = [t for t in items if t.kind == kind]
        if start_date:
            items = [t for t in items if t.date >= start_date]
        if end_date:
            items = [t for t in items if t.date <= end_date]
        items.sort(key=lambda t: t.date)
        return {"status": "ok", "output": [self._tx_summary(t) for t in items]}

    def get_transaction(self, txid: str) -> Dict:
        t = self.transactions.get(txid)
        if not t:
            return {"status": "failed", "output": f"transaction {txid} not found"}
        return {"status": "ok", "output": asdict(t)}

    def create_transaction(self, category_id: str, amount: float, date: str,
                           description: str = "", currency: str = "USD",
                           kind: str = "expense") -> Dict:
        if category_id not in self.categories:
            return {"status": "failed", "output": f"category {category_id} not found"}
        if kind not in TX_KINDS:
            return {"status": "failed", "output": f"kind must be one of {TX_KINDS}"}
        t = Transaction(
            txid=self.uuid(),
            category_id=category_id,
            amount=float(amount),
            currency=currency,
            date=date,
            description=description,
            kind=kind,
        )
        self.transactions[t.txid] = t
        self._recompute_budget_spent(self._month_of(date), category_id)
        return {"status": "ok", "output": self._tx_summary(t)}

    def update_transaction(self, txid: str,
                           category_id: Optional[str] = None,
                           amount: Optional[float] = None,
                           date: Optional[str] = None,
                           description: Optional[str] = None,
                           currency: Optional[str] = None,
                           kind: Optional[str] = None) -> Dict:
        t = self.transactions.get(txid)
        if not t:
            return {"status": "failed", "output": f"transaction {txid} not found"}
        if category_id is not None and category_id not in self.categories:
            return {"status": "failed", "output": f"category {category_id} not found"}
        if kind is not None and kind not in TX_KINDS:
            return {"status": "failed", "output": f"kind must be one of {TX_KINDS}"}
        old_month = self._month_of(t.date)
        old_cat = t.category_id
        if category_id is not None:
            t.category_id = category_id
        if amount is not None:
            t.amount = float(amount)
        if date is not None:
            t.date = date
        if description is not None:
            t.description = description
        if currency is not None:
            t.currency = currency
        if kind is not None:
            t.kind = kind
        self._recompute_budget_spent(old_month, old_cat)
        self._recompute_budget_spent(self._month_of(t.date), t.category_id)
        return {"status": "ok", "output": self._tx_summary(t)}

    def delete_transaction(self, txid: str) -> Dict:
        t = self.transactions.pop(txid, None)
        if not t:
            return {"status": "failed", "output": f"transaction {txid} not found"}
        self._recompute_budget_spent(self._month_of(t.date), t.category_id)
        return {"status": "ok", "output": {"txid": txid, "deleted": True}}

    def list_budgets(self, month: Optional[str] = None) -> Dict:
        items = list(self.budgets.values())
        if month:
            items = [b for b in items if b.month == month]
        items.sort(key=lambda b: (b.month, b.category_id))
        return {"status": "ok", "output": [asdict(b) for b in items]}

    def get_budget(self, bid: str) -> Dict:
        b = self.budgets.get(bid)
        if not b:
            return {"status": "failed", "output": f"budget {bid} not found"}
        return {"status": "ok", "output": asdict(b)}

    def set_budget(self, month: str, category_id: str, limit: float) -> Dict:
        if category_id not in self.categories:
            return {"status": "failed", "output": f"category {category_id} not found"}
        existing = None
        for b in self.budgets.values():
            if b.month == month and b.category_id == category_id:
                existing = b
                break
        if existing:
            existing.limit = float(limit)
            self._recompute_budget_spent(month, category_id)
            return {"status": "ok", "output": asdict(existing)}
        b = Budget(
            bid=self.uuid(),
            month=month,
            category_id=category_id,
            limit=float(limit),
            spent=0.0,
        )
        self.budgets[b.bid] = b
        self._recompute_budget_spent(month, category_id)
        return {"status": "ok", "output": asdict(b)}

    def get_spending_by_category(self, month: str) -> Dict:
        result: Dict[str, float] = {catid: 0.0 for catid in self.categories}
        for t in self.transactions.values():
            if t.kind == "expense" and self._month_of(t.date) == month:
                result[t.category_id] = result.get(t.category_id, 0.0) + t.amount
        rounded = {k: round(v, 2) for k, v in result.items()}
        return {"status": "ok", "output": {"month": month, "by_category": rounded}}

    def get_monthly_summary(self, month: str) -> Dict:
        income = 0.0
        expense = 0.0
        for t in self.transactions.values():
            if self._month_of(t.date) != month:
                continue
            if t.kind == "income":
                income += t.amount
            elif t.kind == "expense":
                expense += t.amount
        return {
            "status": "ok",
            "output": {
                "month": month,
                "income": round(income, 2),
                "expense": round(expense, 2),
                "net": round(income - expense, 2),
            },
        }

    def search_transactions(self, query: str) -> Dict:
        q = query.lower()
        items = [t for t in self.transactions.values()
                 if q in t.description.lower() or q in t.category_id.lower()]
        items.sort(key=lambda t: t.date)
        return {"status": "ok", "output": [self._tx_summary(t) for t in items]}

    def get_savings_rate(self, month: str) -> Dict:
        income = 0.0
        expense = 0.0
        for t in self.transactions.values():
            if self._month_of(t.date) != month:
                continue
            if t.kind == "income":
                income += t.amount
            elif t.kind == "expense":
                expense += t.amount
        rate = 0.0 if income <= 0 else round((income - expense) / income, 4)
        return {
            "status": "ok",
            "output": {
                "month": month,
                "income": round(income, 2),
                "expense": round(expense, 2),
                "savings_rate": rate,
            },
        }

    def get_stats(self) -> Dict:
        by_kind: Dict[str, int] = {k: 0 for k in TX_KINDS}
        by_category: Dict[str, int] = {cid: 0 for cid in self.categories}
        total_income = 0.0
        total_expense = 0.0
        for t in self.transactions.values():
            by_kind[t.kind] = by_kind.get(t.kind, 0) + 1
            by_category[t.category_id] = by_category.get(t.category_id, 0) + 1
            if t.kind == "income":
                total_income += t.amount
            elif t.kind == "expense":
                total_expense += t.amount
        return {
            "status": "ok",
            "output": {
                "categories": len(self.categories),
                "transactions": len(self.transactions),
                "budgets": len(self.budgets),
                "by_kind": by_kind,
                "by_category": by_category,
                "total_income": round(total_income, 2),
                "total_expense": round(total_expense, 2),
            },
        }
