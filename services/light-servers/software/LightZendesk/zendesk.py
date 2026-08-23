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
    if v is None or str(v).strip() == "":
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _opt_csv_list(v, sep=";"):
    if not v:
        return []
    return [x for x in str(v).split(sep) if x]


VALID_STATUS = {"new", "open", "pending", "hold", "solved", "closed"}
VALID_PRIORITY = {"low", "normal", "high", "urgent"}


class ZendeskSession:
    """Deterministic sandbox for the Zendesk Support API mock, ported from the FastAPI service."""

    def __init__(self, os_cfg, seed=None):
        # Seedless: world loaded verbatim from a frozen snapshot next to
        # this module; `seed` is accepted for client compat and ignored.
        if seed_mode():
            # Seed architecture: world rolled from a seed (re-armed).
            self.rng = random.Random(resolve_seed(seed))
            self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()
            self.time_machine = TimeMachine(rng=self.rng)

            from software.utils.world_data import load_state as _load_state
            _load_state(self, "LightZendesk")
        else:
            # Seedless: world loaded verbatim from the frozen snapshot.
            restore_into(self, Path(__file__).resolve().parent / "world.pkl")
            self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()

    def get_session_dict(self):
        return {"tickets": self.tickets, "comments": self.comments}

    # --- helpers -----------------------------------------------------------
    def _now(self) -> str:
        return self.os.now()

    def _next_id(self, store):
        return (max((x["id"] for x in store), default=None) + 1) if store else 1

    def _find(self, store, obj_id):
        obj_id = _to_int(obj_id)
        return next((x for x in store if x["id"] == obj_id), None)

    # --- Tickets -----------------------------------------------------------
    def list_tickets(self, status: str | None = None, priority: str | None = None,
                     assignee_id: int | None = None) -> Dict[str, Any]:
        results = list(self.tickets)
        if status:
            results = [t for t in results if t["status"] == status]
        if priority:
            results = [t for t in results if t["priority"] == priority]
        if assignee_id is not None:
            results = [t for t in results if t["assignee_id"] == _to_int(assignee_id)]
        results.sort(key=lambda t: t["id"])
        return {"status": "ok", "output": {"tickets": results, "count": len(results)}}

    def get_ticket(self, ticket_id: int) -> Dict[str, Any]:
        t = self._find(self.tickets, ticket_id)
        if not t:
            return {"status": "failed", "output": f"Ticket {ticket_id} not found"}
        return {"status": "ok", "output": {"ticket": t}}

    def create_ticket(self, subject: str, description: str | None = None, priority: str = "normal",
                      ticket_type: str = "question", requester_id: int | None = None,
                      assignee_id: int | None = None, organization_id: int | None = None,
                      tags: List[str] | None = None, comment_body: str | None = None) -> Dict[str, Any]:
        if not subject:
            return {"status": "failed", "output": "subject is required"}
        if priority and priority not in VALID_PRIORITY:
            return {"status": "failed", "output": f"Invalid priority: {priority}"}
        now = self._now()
        ticket_id = self._next_id(self.tickets)
        ticket = {
            "id": ticket_id,
            "subject": subject,
            "description": description or (comment_body or ""),
            "status": "new",
            "priority": priority or "normal",
            "type": ticket_type or "question",
            "requester_id": _to_int(requester_id),
            "assignee_id": _to_int(assignee_id),
            "organization_id": _to_int(organization_id),
            "tags": tags or [],
            "created_at": now,
            "updated_at": now,
        }
        self.tickets.append(ticket)
        body = comment_body or description
        if body:
            self.comments.append({
                "id": self._next_id(self.comments),
                "ticket_id": ticket_id,
                "author_id": _to_int(requester_id),
                "body": body,
                "public": True,
                "created_at": now,
            })
        return {"status": "ok", "output": {"ticket": ticket}}

    def update_ticket(self, ticket_id: int, status: str | None = None, priority: str | None = None,
                      assignee_id: int | None = None, ticket_type: str | None = None,
                      tags: List[str] | None = None, comment_body: str | None = None,
                      comment_public: bool = True, comment_author_id: int | None = None) -> Dict[str, Any]:
        t = self._find(self.tickets, ticket_id)
        if not t:
            return {"status": "failed", "output": f"Ticket {ticket_id} not found"}
        if status is not None:
            if status not in VALID_STATUS:
                return {"status": "failed", "output": f"Invalid status: {status}"}
            t["status"] = status
        if priority is not None:
            if priority not in VALID_PRIORITY:
                return {"status": "failed", "output": f"Invalid priority: {priority}"}
            t["priority"] = priority
        if assignee_id is not None:
            t["assignee_id"] = _to_int(assignee_id)
        if ticket_type is not None:
            t["type"] = ticket_type
        if tags is not None:
            t["tags"] = tags
        if comment_body:
            self.comments.append({
                "id": self._next_id(self.comments),
                "ticket_id": t["id"],
                "author_id": _to_int(comment_author_id) if comment_author_id is not None else t["assignee_id"],
                "body": comment_body,
                "public": bool(comment_public),
                "created_at": self._now(),
            })
        t["updated_at"] = self._now()
        return {"status": "ok", "output": {"ticket": t}}

    # --- Comments ----------------------------------------------------------
    def list_comments(self, ticket_id: int) -> Dict[str, Any]:
        if not self._find(self.tickets, ticket_id):
            return {"status": "failed", "output": f"Ticket {ticket_id} not found"}
        tid = _to_int(ticket_id)
        comments = [c for c in self.comments if c["ticket_id"] == tid]
        comments.sort(key=lambda c: c["created_at"])
        return {"status": "ok", "output": {"comments": comments, "count": len(comments)}}

    def create_comment(self, ticket_id: int, body: str, author_id: int | None = None,
                       public: bool = True) -> Dict[str, Any]:
        t = self._find(self.tickets, ticket_id)
        if not t:
            return {"status": "failed", "output": f"Ticket {ticket_id} not found"}
        if not body:
            return {"status": "failed", "output": "comment body is required"}
        comment = {
            "id": self._next_id(self.comments),
            "ticket_id": t["id"],
            "author_id": _to_int(author_id) if author_id is not None else t["assignee_id"],
            "body": body,
            "public": bool(public),
            "created_at": self._now(),
        }
        self.comments.append(comment)
        t["updated_at"] = self._now()
        return {"status": "ok", "output": {"comment": comment}}

    # --- Users / Organizations ---------------------------------------------
    def list_users(self, role: str | None = None) -> Dict[str, Any]:
        results = list(self.users)
        if role:
            results = [u for u in results if u["role"] == role]
        return {"status": "ok", "output": {"users": results, "count": len(results)}}

    def get_user(self, user_id: int) -> Dict[str, Any]:
        u = self._find(self.users, user_id)
        if not u:
            return {"status": "failed", "output": f"User {user_id} not found"}
        return {"status": "ok", "output": {"user": u}}

    def list_organizations(self) -> Dict[str, Any]:
        return {"status": "ok", "output": {"organizations": list(self.organizations), "count": len(self.organizations)}}


if __name__ == "__main__":
    s = ZendeskSession(seed=12)
    print(s.list_tickets())
    print(s.list_organizations())
