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


class WhatsappSession:
    """Deterministic sandbox for the WhatsApp Cloud API mock, ported from the FastAPI service."""

    def __init__(self, os_cfg, seed=None, fixture=None):
        # Seedless: world loaded verbatim from a frozen snapshot next to
        # this module; `seed` is accepted for client compat and ignored.
        if seed_mode():
            # Seed architecture: world rolled from a seed (re-armed).
            self.rng = random.Random(resolve_seed(seed))
            self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()
            self.time_machine = TimeMachine(rng=self.rng)

            with open(CORPUS_PATH / "whatsapp.yaml") as f:
                info = yaml.safe_load(f)

            self.business: Dict[str, Any] = dict(info.get("business", {}))
            self.contacts: List[Dict[str, Any]] = [
                {**c, "opted_in": _to_bool(c.get("opted_in", False))} for c in info.get("contacts", [])
            ]
            self.conversations: List[Dict[str, Any]] = [
                {**c, "within_24h_window": _to_bool(c.get("within_24h_window", False))}
                for c in info.get("conversations", [])
            ]
            self.templates: List[Dict[str, Any]] = list(info.get("templates", []))
            self.messages: List[Dict[str, Any]] = list(info.get("messages", []))

            from software.utils.fixtures import apply as _apply_fixtures
            _apply_fixtures(self, "LightWhatsApp", fixture)
            from software.utils.world_data import hydrate as _hydrate_world_data
            _hydrate_world_data(self, "LightWhatsApp")
        else:
            # Seedless: world loaded verbatim from the frozen snapshot.
            restore_into(self, Path(__file__).resolve().parent / "world.pkl")
            self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()

    def get_session_dict(self):
        return {"messages": self.messages, "conversations": self.conversations}

    # --- helpers -----------------------------------------------------------
    def _now(self) -> str:
        return self.os.now()

    def uuid(self) -> str:
        alphabet = "0123456789abcdef"
        return ''.join(self.rng.choices(alphabet, k=24))

    def _new_message_id(self) -> str:
        return f"wamid.{self.uuid().upper()}"

    # --- Business ----------------------------------------------------------
    def get_business(self) -> Dict[str, Any]:
        return {"status": "ok", "output": dict(self.business)}

    # --- Contacts ----------------------------------------------------------
    def list_contacts(self, opted_in_only: bool = False) -> Dict[str, Any]:
        results = list(self.contacts)
        if opted_in_only:
            results = [c for c in results if c["opted_in"]]
        return {"status": "ok", "output": [dict(c) for c in results]}

    def get_contact(self, wa_id: str) -> Dict[str, Any]:
        for c in self.contacts:
            if c["wa_id"] == wa_id:
                return {"status": "ok", "output": dict(c)}
        return {"status": "failed", "output": f"Contact {wa_id} not found"}

    # --- Templates ---------------------------------------------------------
    def list_templates(self, status: str | None = None) -> Dict[str, Any]:
        results = list(self.templates)
        if status:
            results = [t for t in results if t["status"].upper() == status.upper()]
        return {"status": "ok", "output": [dict(t) for t in results]}

    def get_template(self, name: str) -> Dict[str, Any]:
        for t in self.templates:
            if t["name"] == name:
                return {"status": "ok", "output": dict(t)}
        return {"status": "failed", "output": f"Template {name} not found"}

    # --- Conversations / messages ------------------------------------------
    def list_conversations(self, wa_id: str | None = None) -> Dict[str, Any]:
        results = list(self.conversations)
        if wa_id:
            results = [c for c in results if c["wa_id"] == wa_id]
        results.sort(key=lambda c: c["last_message_at"], reverse=True)
        return {"status": "ok", "output": [dict(c) for c in results]}

    def list_messages(self, conversation_id: str | None = None, wa_id: str | None = None,
                      limit: int = 20) -> Dict[str, Any]:
        results = list(self.messages)
        if conversation_id:
            results = [m for m in results if m["conversation_id"] == conversation_id]
        elif wa_id:
            conv_ids = {c["conversation_id"] for c in self.conversations if c["wa_id"] == wa_id}
            results = [m for m in results if m["conversation_id"] in conv_ids]
        results.sort(key=lambda m: m["sent_at"], reverse=True)
        return {"status": "ok", "output": [dict(m) for m in results[:limit]]}

    def send_text(self, to_wa_id: str, body: str) -> Dict[str, Any]:
        contact = next((c for c in self.contacts if c["wa_id"] == to_wa_id), None)
        if not contact:
            return {"status": "failed", "output": f"Contact {to_wa_id} not found"}
        if not contact["opted_in"]:
            return {"status": "failed", "output": "Recipient has not opted in to messages"}
        conv = next((c for c in self.conversations if c["wa_id"] == to_wa_id), None)
        if not conv or not conv["within_24h_window"]:
            return {"status": "failed", "output": "Outside 24-hour customer service window; use a template message"}

        msg_id = self._new_message_id()
        now = self._now()
        msg = {
            "message_id": msg_id,
            "conversation_id": conv["conversation_id"],
            "direction": "outbound",
            "from_wa_id": self.business["phone_number_id"].replace("PNI-", ""),
            "to_wa_id": to_wa_id,
            "type": "text",
            "text": body,
            "template_name": "",
            "status": "sent",
            "sent_at": now,
        }
        self.messages.append(msg)
        for c in self.conversations:
            if c["conversation_id"] == conv["conversation_id"]:
                c["last_message_at"] = now
        return {"status": "ok", "output": {"messages": [{"id": msg_id, "message_status": "accepted"}]}}

    def send_template(self, to_wa_id: str, template_name: str,
                     components: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
        contact = next((c for c in self.contacts if c["wa_id"] == to_wa_id), None)
        if not contact:
            return {"status": "failed", "output": f"Contact {to_wa_id} not found"}
        template = next((t for t in self.templates if t["name"] == template_name), None)
        if not template:
            return {"status": "failed", "output": f"Template {template_name} not found"}
        if template["status"].upper() != "APPROVED":
            return {"status": "failed",
                    "output": f"Template {template_name} is not approved (status: {template['status']})"}

        conv = next((c for c in self.conversations if c["wa_id"] == to_wa_id), None)
        if not conv:
            conv = {
                "conversation_id": f"conv-{self.uuid()[:6]}",
                "wa_id": to_wa_id,
                "started_at": self._now(),
                "last_message_at": self._now(),
                "origin": "business_initiated",
                "within_24h_window": True,
            }
            self.conversations.append(conv)

        msg_id = self._new_message_id()
        now = self._now()
        msg = {
            "message_id": msg_id,
            "conversation_id": conv["conversation_id"],
            "direction": "outbound",
            "from_wa_id": self.business["phone_number_id"].replace("PNI-", ""),
            "to_wa_id": to_wa_id,
            "type": "template",
            "text": "",
            "template_name": template_name,
            "status": "sent",
            "sent_at": now,
        }
        self.messages.append(msg)
        for c in self.conversations:
            if c["conversation_id"] == conv["conversation_id"]:
                c["last_message_at"] = now
        return {"status": "ok", "output": {"messages": [{"id": msg_id, "message_status": "accepted"}]}}

    def mark_read(self, message_id: str) -> Dict[str, Any]:
        for m in self.messages:
            if m["message_id"] == message_id:
                m["status"] = "read"
                return {"status": "ok", "output": {"success": True, "message_id": message_id}}
        return {"status": "failed", "output": f"Message {message_id} not found"}


if __name__ == "__main__":
    s = WhatsappSession(seed=12)
    print(s.get_business())
    print(s.list_contacts())
