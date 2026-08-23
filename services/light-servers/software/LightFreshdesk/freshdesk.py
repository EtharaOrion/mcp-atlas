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


def _to_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


class FreshdeskSession:
    """Deterministic sandbox for the Freshdesk mock, ported from the FastAPI service.

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

            # World data loaded verbatim from corpus/state.json (no cooking):
            # tickets/contacts/agents stored in final shape.
            from software.utils.world_data import load_state as _load_state
            _load_state(self, 'LightFreshdesk')
        else:
            # Seedless: world loaded verbatim from the frozen snapshot.
            restore_into(self, Path(__file__).resolve().parent / "world.pkl")
            self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()

    def get_session_dict(self):
        return {"tickets": self.tickets}

    # --- helpers -----------------------------------------------------------
    def _now(self) -> str:
        return self.os.now()

    def _next_ticket_id(self) -> int:
        return max((t["id"] for t in self.tickets), default=70000) + 1

    # --- Tickets -----------------------------------------------------------
    def list_tickets(self, status: int | None = None, priority: int | None = None,
                     requester_id: int | None = None) -> Dict[str, Any]:
        tickets = list(self.tickets)
        if status is not None:
            tickets = [t for t in tickets if t["status"] == int(status)]
        if priority is not None:
            tickets = [t for t in tickets if t["priority"] == int(priority)]
        if requester_id is not None:
            tickets = [t for t in tickets if t["requester_id"] == int(requester_id)]
        return {"status": "ok", "output": tickets}

    def get_ticket(self, ticket_id: int) -> Dict[str, Any]:
        t = next((x for x in self.tickets if x["id"] == int(ticket_id)), None)
        if not t:
            return {"status": "failed", "output": f"Ticket {ticket_id} not found"}
        return {"status": "ok", "output": t}

    def create_ticket(self, subject: str | None = None, description: str | None = None,
                      status: int | None = None, priority: int | None = None,
                      requester_id: int | None = None, responder_id: int | None = None,
                      type: str | None = None, tags: List[str] | None = None) -> Dict[str, Any]:
        now = self._now()
        ticket = {
            "id": self._next_ticket_id(),
            "subject": subject or "",
            "description": description or "",
            "status": int(status or 2),
            "priority": int(priority or 1),
            "requester_id": _to_int(requester_id),
            "responder_id": _to_int(responder_id),
            "type": type or "Question",
            "tags": tags or [],
            "created_at": now,
            "updated_at": now,
        }
        self.tickets.append(ticket)
        return {"status": "ok", "output": ticket}

    def update_ticket(self, ticket_id: int, subject: str | None = None,
                      description: str | None = None, status: int | None = None,
                      priority: int | None = None, responder_id: int | None = None,
                      requester_id: int | None = None, type: str | None = None,
                      tags: List[str] | None = None) -> Dict[str, Any]:
        payload = {
            "subject": subject,
            "description": description,
            "status": status,
            "priority": priority,
            "responder_id": responder_id,
            "requester_id": requester_id,
            "type": type,
            "tags": tags,
        }
        for i, t in enumerate(self.tickets):
            if t["id"] == int(ticket_id):
                for field in ("subject", "description", "type"):
                    if payload.get(field) is not None:
                        self.tickets[i][field] = payload[field]
                for field in ("status", "priority", "responder_id", "requester_id"):
                    if payload.get(field) is not None:
                        self.tickets[i][field] = int(payload[field])
                if payload.get("tags") is not None:
                    self.tickets[i]["tags"] = payload["tags"]
                self.tickets[i]["updated_at"] = self._now()
                return {"status": "ok", "output": self.tickets[i]}
        return {"status": "failed", "output": f"Ticket {ticket_id} not found"}

    # --- Contacts + agents -------------------------------------------------
    def list_contacts(self) -> Dict[str, Any]:
        return {"status": "ok", "output": list(self.contacts)}

    def list_agents(self) -> Dict[str, Any]:
        return {"status": "ok", "output": list(self.agents)}


if __name__ == "__main__":
    s = FreshdeskSession(seed=12)
    print(s.list_tickets())
    print(s.list_agents())
