import random
from typing import Dict, List, Any
from pathlib import Path
import yaml
import sys
from copy import deepcopy
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


def _strict_int(v) -> int:
    return int(v)


def _opt_int(v, default=None):
    if v is None or v == "":
        return default
    return int(v)


def _opt_str(v, default=""):
    if v is None:
        return default
    return str(v)


class TelegramSession:
    """Deterministic sandbox for the Telegram Bot API mock, ported from the FastAPI service.

    All API methods return the Light envelope; the source Telegram
    {"ok": true, "result": X} maps to output X and {"ok": false, ...} to failure.
    """

    def __init__(self, os_cfg, seed=None):
        # Seedless: world loaded verbatim from a frozen snapshot next to
        # this module; `seed` is accepted for client compat and ignored.
        if seed_mode():
            # Seed architecture: world rolled from a seed (re-armed).
            self.rng = random.Random(resolve_seed(seed))
            self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()
            self.time_machine = TimeMachine(rng=self.rng)

            with open(CORPUS_PATH / "telegram.yaml") as f:
                info = yaml.safe_load(f)

            self.bot: Dict[str, Any] = dict(info.get("bot", {}))
            self.users: List[Dict[str, Any]] = [
                {
                    "id": _strict_int(r["id"]),
                    "is_bot": _to_bool(r["is_bot"]),
                    "first_name": r["first_name"],
                    "last_name": (_opt_str(r.get("last_name"), "") or None),
                    "username": (_opt_str(r.get("username"), "") or None),
                    "language_code": (_opt_str(r.get("language_code"), "") or None),
                }
                for r in info.get("users", [])
            ]
            self.chats: List[Dict[str, Any]] = []
            for r in info.get("chats", []):
                chat = {"id": _strict_int(r["id"]), "type": r["type"]}
                if r["title"]:
                    chat["title"] = r["title"]
                if r["username"]:
                    chat["username"] = r["username"]
                if r["first_name"]:
                    chat["first_name"] = r["first_name"]
                if r["last_name"]:
                    chat["last_name"] = r["last_name"]
                if r["description"]:
                    chat["description"] = r["description"]
                chat["member_count"] = _strict_int(r["member_count"])
                self.chats.append(chat)
            self.messages: List[Dict[str, Any]] = [
                {
                    "message_id": _strict_int(r["message_id"]),
                    "chat_id": _strict_int(r["chat_id"]),
                    "from_id": _strict_int(r["from_id"]),
                    "text": r["text"],
                    "date": _strict_int(r["date"]),
                    "reply_to_message_id": _opt_int(r.get("reply_to_message_id"), None),
                }
                for r in info.get("messages", [])
            ]
            self.members: List[Dict[str, Any]] = [
                {
                    "chat_id": _strict_int(r["chat_id"]),
                    "user_id": _strict_int(r["user_id"]),
                    "status": r["status"],
                }
                for r in info.get("chat_members", [])
            ]

            self._next_message_id = max((m["message_id"] for m in self.messages), default=0) + 1
            self._next_update_id = 100001

            from software.utils.world_data import hydrate as _hydrate_world_data
            _hydrate_world_data(self, "LightTelegram")
            # world data may replace messages wholesale (e.g. new/different ids);
            # recompute the id counter from whatever's live now, not the corpus.
            self._next_message_id = max((m["message_id"] for m in self.messages), default=0) + 1
        else:
            # Seedless: world loaded verbatim from the frozen snapshot.
            restore_into(self, Path(__file__).resolve().parent / "world.pkl")
            self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()

    def get_session_dict(self):
        return {"messages": self.messages}

    # --- helpers -----------------------------------------------------------
    def _now(self) -> int:
        try:
            return int(datetime.strptime(self.os.now(), "%Y-%m-%d %H:%M:%S")
                       .replace(tzinfo=timezone.utc).timestamp())
        except (ValueError, TypeError):
            return 0

    def uuid(self) -> str:
        alphabet = "0123456789"
        return ''.join(self.rng.choices(alphabet, k=16))

    def _ok(self, result):
        return {"status": "ok", "output": result}

    def _err(self, description):
        return {"status": "failed", "output": description}

    def _find_user(self, user_id):
        return next((u for u in self.users if u["id"] == int(user_id)), None)

    def _find_chat(self, chat_id):
        return next((c for c in self.chats if c["id"] == int(chat_id)), None)

    def _from_user(self, user_id):
        u = self._find_user(user_id)
        if u:
            return {k: u[k] for k in ("id", "is_bot", "first_name", "last_name", "username") if u.get(k) is not None}
        return {"id": int(user_id), "is_bot": False, "first_name": "Unknown"}

    def _chat_stub(self, chat):
        return {k: v for k, v in chat.items() if k != "member_count"}

    def _format_message(self, m):
        chat = self._find_chat(m["chat_id"]) or {"id": m["chat_id"], "type": "private"}
        msg = {
            "message_id": m["message_id"],
            "from": self._from_user(m["from_id"]),
            "chat": self._chat_stub(chat),
            "date": m["date"],
            "text": m["text"],
        }
        if m.get("reply_to_message_id"):
            msg["reply_to_message_id"] = m["reply_to_message_id"]
        return msg

    # --- Bot identity ------------------------------------------------------
    def get_me(self):
        return self._ok(self.bot)

    # --- Sending / editing / deleting messages -----------------------------
    def send_message(self, chat_id: int, text: str, reply_to_message_id: int | None = None):
        if not self._find_chat(chat_id):
            return self._err(f"Bad Request: chat {chat_id} not found")
        msg = {
            "message_id": self._next_message_id,
            "chat_id": int(chat_id),
            "from_id": self.bot["id"],
            "text": text,
            "date": self._now(),
            "reply_to_message_id": int(reply_to_message_id) if reply_to_message_id else None,
        }
        self._next_message_id += 1
        self.messages.append(msg)
        return self._ok(self._format_message(msg))

    def send_photo(self, chat_id: int, photo: str, caption: str | None = None):
        if not self._find_chat(chat_id):
            return self._err(f"Bad Request: chat {chat_id} not found")
        msg = {
            "message_id": self._next_message_id,
            "chat_id": int(chat_id),
            "from_id": self.bot["id"],
            "text": caption or "",
            "date": self._now(),
            "reply_to_message_id": None,
        }
        self._next_message_id += 1
        self.messages.append(msg)
        formatted = self._format_message(msg)
        formatted.pop("text", None)
        if caption:
            formatted["caption"] = caption
        formatted["photo"] = [{"file_id": photo, "width": 1280, "height": 720}]
        return self._ok(formatted)

    def edit_message_text(self, chat_id: int, message_id: int, text: str):
        for m in self.messages:
            if m["chat_id"] == int(chat_id) and m["message_id"] == int(message_id):
                m["text"] = text
                edited = self._format_message(m)
                edited["edit_date"] = self._now()
                return self._ok(edited)
        return self._err("Bad Request: message to edit not found")

    def delete_message(self, chat_id: int, message_id: int):
        for i, m in enumerate(self.messages):
            if m["chat_id"] == int(chat_id) and m["message_id"] == int(message_id):
                self.messages.pop(i)
                return self._ok(True)
        return self._err("Bad Request: message to delete not found")

    # --- Chats / members / updates -----------------------------------------
    def get_chat(self, chat_id: int):
        chat = self._find_chat(chat_id)
        if not chat:
            return self._err(f"Bad Request: chat {chat_id} not found")
        return self._ok(deepcopy(chat))

    def get_chat_member(self, chat_id: int, user_id: int):
        if not self._find_chat(chat_id):
            return self._err(f"Bad Request: chat {chat_id} not found")
        user = self._find_user(user_id)
        if not user:
            return self._err(f"Bad Request: user {user_id} not found")
        member = next((mb for mb in self.members
                       if mb["chat_id"] == int(chat_id) and mb["user_id"] == int(user_id)), None)
        status = member["status"] if member else "left"
        return self._ok({"user": self._from_user(user_id), "status": status})

    def get_updates(self, offset: int | None = None, limit: int = 100):
        updates = []
        update_id = self._next_update_id
        ordered = sorted(self.messages, key=lambda m: (m["date"], m["message_id"]))
        for m in ordered:
            updates.append({
                "update_id": update_id,
                "message": self._format_message(m),
            })
            update_id += 1
        if offset is not None:
            updates = [u for u in updates if u["update_id"] >= int(offset)]
        return self._ok(updates[:limit])


if __name__ == "__main__":
    s = TelegramSession(seed=12)
    print(s.get_me())
    print(s.get_updates())
