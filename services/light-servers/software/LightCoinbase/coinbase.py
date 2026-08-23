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
    return str(v).strip().lower() in ("true", "1", "yes", "t", "y")


def _to_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class CoinbaseSession:
    """Deterministic sandbox for the Coinbase mock, ported from the FastAPI service.

    State is loaded from the corpus at init; subsequent calls read and mutate the
    in-memory tables so repeated calls within a session stay consistent.
    """

    def __init__(self, os_cfg, seed=None):
        # Seedless: world loaded verbatim from a frozen snapshot next to
        # this module; `seed` is accepted for client compat and ignored.
        if seed_mode():
            # Seed architecture: world rolled from a seed (re-armed).
            self.rng = random.Random(resolve_seed(seed))
            self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()
            self.time_machine = TimeMachine(rng=self.rng)

            with open(CORPUS_PATH / "coinbase.yaml") as f:
                info = yaml.safe_load(f)

            self.accounts: List[Dict[str, Any]] = self._coerce_accounts(info.get("accounts", []))
            self.prices: List[Dict[str, Any]] = self._coerce_prices(info.get("prices", []))
            self.transactions: List[Dict[str, Any]] = self._coerce_transactions(info.get("transactions", []))
            self.user: Dict[str, Any] = dict(info.get("user", {}))

            from software.utils.world_data import hydrate as _hydrate_world_data
            _hydrate_world_data(self, "LightCoinbase")
        else:
            # Seedless: world loaded verbatim from the frozen snapshot.
            restore_into(self, Path(__file__).resolve().parent / "world.pkl")
            self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()

    def get_session_dict(self):
        return {"accounts": self.accounts, "transactions": self.transactions}

    # --- coercion ----------------------------------------------------------
    def _coerce_accounts(self, rows):
        out = []
        for r in rows:
            out.append({
                "id": r["id"],
                "name": r["name"],
                "primary": _to_bool(r["primary"]),
                "type": r["type"],
                "currency": {"code": r["currency_code"], "name": r["currency_name"]},
                "balance": {"amount": r["balance_amount"], "currency": r["currency_code"]},
                "native_balance": {"amount": r["native_balance_amount"], "currency": r["native_currency"]},
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "_balance_num": _to_float(r.get("balance_amount"), 0.0),
                "_native_num": _to_float(r.get("native_balance_amount"), 0.0),
            })
        return out

    def _coerce_prices(self, rows):
        return [{"pair": r["pair"], "base": r["base"], "currency": r["currency"],
                 "amount": r["amount"], "_amount_num": _to_float(r.get("amount"), 0.0)}
                for r in rows]

    def _coerce_transactions(self, rows):
        out = []
        for r in rows:
            out.append({
                "id": r["id"],
                "account_id": r["account_id"],
                "type": r["type"],
                "status": r["status"],
                "amount": {"amount": r["amount"], "currency": r["currency"]},
                "native_amount": {"amount": r["native_amount"], "currency": r["native_currency"]},
                "description": r["description"],
                "created_at": r["created_at"],
                "updated_at": r["created_at"],
            })
        return out

    # --- helpers -----------------------------------------------------------
    def _now(self) -> str:
        return self.os.now()

    def uuid(self) -> str:
        alphabet = "0123456789abcdef"
        parts = [8, 4, 4, 4, 12]
        return "-".join("".join(self.rng.choices(alphabet, k=n)) for n in parts)

    def _public_account(self, a):
        return {k: v for k, v in a.items() if not k.startswith("_")}

    def _find_account(self, account_id):
        return next((a for a in self.accounts if a["id"] == account_id), None)

    def _price_for(self, currency_code):
        return next((x for x in self.prices
                     if x["base"] == currency_code and x["currency"] == "USD"), None)

    def _fmt_crypto(self, value):
        return f"{value:.8f}"

    def _fmt_fiat(self, value):
        return f"{value:.2f}"

    # --- API methods -------------------------------------------------------
    def get_user(self) -> Dict[str, Any]:
        return {"status": "ok", "output": self.user}

    def list_accounts(self) -> Dict[str, Any]:
        return {"status": "ok", "output": [self._public_account(a) for a in self.accounts]}

    def get_account(self, account_id: str) -> Dict[str, Any]:
        a = self._find_account(account_id)
        if not a:
            return {"status": "failed", "output": f"Account {account_id} not found"}
        return {"status": "ok", "output": self._public_account(a)}

    def get_spot_price(self, pair: str) -> Dict[str, Any]:
        p = next((x for x in self.prices if x["pair"].upper() == pair.upper()), None)
        if not p:
            return {"status": "failed", "output": f"No spot price for pair {pair}"}
        return {"status": "ok", "output": {"base": p["base"], "currency": p["currency"], "amount": p["amount"]}}

    def _trade(self, account_id, amount, side):
        account = self._find_account(account_id)
        if not account:
            return {"status": "failed", "output": f"Account {account_id} not found"}
        try:
            qty = float(amount)
        except (TypeError, ValueError):
            return {"status": "failed", "output": "amount must be a number"}
        if qty <= 0:
            return {"status": "failed", "output": "amount must be positive"}

        code = account["currency"]["code"]
        price = self._price_for(code)
        if not price:
            return {"status": "failed", "output": f"No spot price available for {code}"}
        fiat = qty * price["_amount_num"]

        if side == "buy":
            account["_balance_num"] += qty
            account["_native_num"] += fiat
            signed_qty = qty
            signed_fiat = fiat
        else:  # sell
            if qty > account["_balance_num"]:
                return {"status": "failed", "output": f"Insufficient {code} balance to sell {qty}"}
            account["_balance_num"] -= qty
            account["_native_num"] = max(0.0, account["_native_num"] - fiat)
            signed_qty = -qty
            signed_fiat = -fiat

        account["balance"]["amount"] = self._fmt_crypto(account["_balance_num"])
        account["native_balance"]["amount"] = self._fmt_fiat(account["_native_num"])
        account["updated_at"] = self._now()

        txn = {
            "id": self.uuid(),
            "account_id": account_id,
            "type": side,
            "status": "completed",
            "amount": {"amount": self._fmt_crypto(signed_qty), "currency": code},
            "native_amount": {"amount": self._fmt_fiat(signed_fiat), "currency": "USD"},
            "description": f"{side.capitalize()} {qty} {code}",
            "created_at": self._now(),
            "updated_at": self._now(),
        }
        self.transactions.append(txn)

        return {"status": "ok", "output": {
            "id": self.uuid(),
            "status": "completed",
            "resource": side,
            "amount": {"amount": self._fmt_crypto(qty), "currency": code},
            "total": {"amount": self._fmt_fiat(fiat), "currency": "USD"},
            "unit_price": {"amount": price["amount"], "currency": "USD"},
            "account_id": account_id,
            "transaction_id": txn["id"],
            "created_at": txn["created_at"],
        }}

    def create_buy(self, account_id: str, amount: str) -> Dict[str, Any]:
        return self._trade(account_id, amount, "buy")

    def create_sell(self, account_id: str, amount: str) -> Dict[str, Any]:
        return self._trade(account_id, amount, "sell")

    def list_transactions(self, account_id: str) -> Dict[str, Any]:
        if not self._find_account(account_id):
            return {"status": "failed", "output": f"Account {account_id} not found"}
        txns = [t for t in self.transactions if t["account_id"] == account_id]
        txns.sort(key=lambda t: t["created_at"], reverse=True)
        return {"status": "ok", "output": txns}


if __name__ == "__main__":
    s = CoinbaseSession(seed=12)
    print(s.list_accounts())
    print(s.get_spot_price("BTC-USD"))
