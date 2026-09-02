import random
from typing import Dict, List, Any
from pathlib import Path
import yaml
import sys
from datetime import datetime

WORK_DIR = Path('.').__str__()
if WORK_DIR not in sys.path:
    sys.path.append(WORK_DIR)

from software.utils.core import OSConnector, DummyOSConnector, connect_os
from software.utils.world_snapshot import restore_into, seed_mode, resolve_seed
from software.utils.time import TimeMachine

CORPUS_PATH = Path(__file__).resolve().parent / "corpus"


def _to_bool(v) -> bool:
    return str(v).strip().lower() == "true"


def _to_int(v) -> int:
    return int(str(v).strip())


class DiscordSession:
    """Deterministic sandbox for the Discord mock, ported from the FastAPI service.

    State is loaded from the corpus at init; subsequent calls read and mutate the
    in-memory tables so repeated calls within a session stay consistent.
    """

    def __init__(self, os_cfg, seed=None):
        # Seedless: world loaded verbatim from a frozen snapshot next to
        # this module; `seed` is accepted for client compat and ignored.
        if seed_mode():
            # Seed architecture: world rolled from a seed (re-armed).
            self.rng = random.Random(resolve_seed(seed))
            self.os = connect_os(os_cfg)
            self.time_machine = TimeMachine(rng=self.rng)

            # World data loaded verbatim from corpus/state.json (no cooking):
            # me/guilds/channels/messages/members/roles are stored in final shape.
            from software.utils.world_data import load_state as _load_state
            _load_state(self, 'LightDiscord')
        else:
            # Seedless: world loaded verbatim from the frozen snapshot.
            restore_into(self, Path(__file__).resolve().parent / "world.pkl")
            self.os = connect_os(os_cfg)

    def get_session_dict(self):
        return {"messages": self.messages}

    # --- helpers -----------------------------------------------------------
    def _now(self) -> str:
        return self.os.now()

    def uuid(self) -> str:
        alphabet = "0123456789"
        return ''.join(self.rng.choices(alphabet, k=19))

    # --- Users -------------------------------------------------------------
    def get_me(self) -> Dict[str, Any]:
        return {"status": "ok", "output": self.me}

    def list_my_guilds(self) -> Dict[str, Any]:
        return {"status": "ok", "output": [
            {
                "id": g["id"],
                "name": g["name"],
                "icon": g["icon"],
                "owner": g["owner_id"] == self.me["id"],
                "permissions": "104324673",
            }
            for g in self.guilds
        ]}

    # --- Guilds ------------------------------------------------------------
    def get_guild(self, guild_id: str) -> Dict[str, Any]:
        for g in self.guilds:
            if g["id"] == guild_id:
                return {"status": "ok", "output": g}
        return {"status": "failed", "output": f"Unknown Guild {guild_id}"}

    def list_guild_channels(self, guild_id: str) -> Dict[str, Any]:
        if not any(g["id"] == guild_id for g in self.guilds):
            return {"status": "failed", "output": f"Unknown Guild {guild_id}"}
        chans = [c for c in self.channels if c["guild_id"] == guild_id]
        chans.sort(key=lambda c: c["position"])
        return {"status": "ok", "output": chans}

    def list_guild_members(self, guild_id: str, limit: int = 100) -> Dict[str, Any]:
        if not any(g["id"] == guild_id for g in self.guilds):
            return {"status": "failed", "output": f"Unknown Guild {guild_id}"}
        members = [m for m in self.members if m["guild_id"] == guild_id]
        return {"status": "ok", "output": members[: max(1, limit)]}

    def list_guild_roles(self, guild_id: str) -> Dict[str, Any]:
        if not any(g["id"] == guild_id for g in self.guilds):
            return {"status": "failed", "output": f"Unknown Guild {guild_id}"}
        roles = [r for r in self.roles if r["guild_id"] == guild_id]
        roles.sort(key=lambda r: r["position"], reverse=True)
        return {"status": "ok", "output": roles}

    # --- Channels + messages ----------------------------------------------
    def get_channel(self, channel_id: str) -> Dict[str, Any]:
        for c in self.channels:
            if c["id"] == channel_id:
                return {"status": "ok", "output": c}
        return {"status": "failed", "output": f"Unknown Channel {channel_id}"}

    def list_channel_messages(self, channel_id: str, limit: int = 50) -> Dict[str, Any]:
        if not any(c["id"] == channel_id for c in self.channels):
            return {"status": "failed", "output": f"Unknown Channel {channel_id}"}
        msgs = [m for m in self.messages if m["channel_id"] == channel_id]
        msgs.sort(key=lambda m: m["timestamp"], reverse=True)
        return {"status": "ok", "output": msgs[: max(1, limit)]}

    def create_message(self, channel_id: str, content: str, author_id: str | None = None) -> Dict[str, Any]:
        channel = next((c for c in self.channels if c["id"] == channel_id), None)
        if not channel:
            return {"status": "failed", "output": f"Unknown Channel {channel_id}"}
        if not content:
            return {"status": "failed", "output": "Cannot send an empty message"}
        author_id = author_id or self.me["id"]
        member = next((m for m in self.members
                       if m["guild_id"] == channel["guild_id"] and m["user"]["id"] == author_id), None)
        username = member["user"]["username"] if member else self.me["username"]
        msg = {
            "id": self.uuid(),
            "channel_id": channel_id,
            "author": {"id": author_id, "username": username},
            "content": content,
            "timestamp": self._now(),
            "pinned": False,
            "edited_timestamp": None,
        }
        self.messages.append(msg)
        return {"status": "ok", "output": msg}


    def update_message(self, channel_id: str, message_id: str, content: str) -> Dict[str, Any]:
        if not any(c["id"] == channel_id for c in self.channels):
            return {"status": "failed", "output": f"Unknown Channel {channel_id}"}
        if not content:
            return {"status": "failed", "output": "Cannot set empty content"}
        for msg in self.messages:
            if msg["id"] == message_id and msg["channel_id"] == channel_id:
                msg["content"] = content
                msg["edited_timestamp"] = self._now()
                return {"status": "ok", "output": msg}
        return {"status": "failed", "output": f"Message {message_id} not found"}

    def delete_message(self, channel_id: str, message_id: str) -> Dict[str, Any]:
        if not any(c["id"] == channel_id for c in self.channels):
            return {"status": "failed", "output": f"Unknown Channel {channel_id}"}
        for idx, msg in enumerate(self.messages):
            if msg["id"] == message_id and msg["channel_id"] == channel_id:
                self.messages.pop(idx)
                return {"status": "ok", "output": {"id": message_id, "deleted": True}}
        return {"status": "failed", "output": f"Message {message_id} not found"}


if __name__ == "__main__":
    s = DiscordSession(seed=12)
    print(s.get_me())
    print(s.list_my_guilds())
