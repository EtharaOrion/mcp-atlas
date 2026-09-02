import random
from typing import Dict, List, Any
from pathlib import Path
import sys
from datetime import datetime

WORK_DIR = Path('.').__str__()
if WORK_DIR not in sys.path:
    sys.path.append(WORK_DIR)

from software.utils import corpus_registry
from software.utils.core import OSConnector, DummyOSConnector, connect_os
from software.utils.world_snapshot import restore_into, seed_mode, resolve_seed
from software.utils.time import TimeMachine

CORPUS_PATH = Path(__file__).resolve().parent / "corpus"


def _to_bool(v) -> bool:
    return str(v).strip().lower() == "true"


def _to_int(v) -> int:
    return int(str(v).strip())


def _to_float(v) -> float:
    return float(str(v).strip())


def _split_tags(s) -> List[str]:
    return [t for t in (s or "").split(";") if t]


class TwitchSession:
    """Deterministic sandbox for the Twitch Helix API mock, ported from the FastAPI service.

    State is loaded from the corpus at init; subsequent calls read the in-memory
    tables so repeated calls within a session stay consistent.
    """

    def __init__(self, os_cfg, seed=None):
        # Seedless: world loaded verbatim from a frozen snapshot next to
        # this module; `seed` is accepted for client compat and ignored.
        if seed_mode():
            # Seed architecture: world rolled from a seed (re-armed).
            self.rng = random.Random(resolve_seed(seed))
            self.os = connect_os(os_cfg)
            self.time_machine = TimeMachine(rng=self.rng)

            info = corpus_registry.load(CORPUS_PATH / "twitch.yaml")

            self.users: List[Dict[str, Any]] = [
                {**u, "view_count": _to_int(u["view_count"])} for u in info.get("users", [])
            ]
            self.games: List[Dict[str, Any]] = [
                {
                    "id": g["id"],
                    "name": g["name"],
                    "box_art_url": g["box_art_url"],
                    "rank": _to_int(g["rank"]),
                    "viewer_count": _to_int(g["viewer_count"]),
                }
                for g in info.get("games", [])
            ]
            self.channels: List[Dict[str, Any]] = [
                {
                    **c,
                    "tags": _split_tags(c["tags"]),
                    "follower_count": _to_int(c["follower_count"]),
                }
                for c in info.get("channels", [])
            ]
            self.streams: List[Dict[str, Any]] = [
                {
                    **s,
                    "viewer_count": _to_int(s["viewer_count"]),
                    "is_live": _to_bool(s["is_live"]),
                    "started_at": (str(s.get("started_at") or "") or None),
                }
                for s in info.get("streams", [])
            ]
            self.clips: List[Dict[str, Any]] = [
                {
                    **c,
                    "view_count": _to_int(c["view_count"]),
                    "duration": _to_float(c["duration"]),
                }
                for c in info.get("clips", [])
            ]
            from software.utils.world_data import hydrate as _hydrate_world_data
            _hydrate_world_data(self, 'LightTwitch')
        else:
            # Seedless: world loaded verbatim from the frozen snapshot.
            restore_into(self, Path(__file__).resolve().parent / "world.pkl")
            self.os = connect_os(os_cfg)

    def get_session_dict(self):
        return {"users": self.users, "streams": self.streams}

    # --- helpers -----------------------------------------------------------
    def _now(self) -> str:
        return self.os.now()

    def uuid(self) -> str:
        alphabet = "0123456789"
        return ''.join(self.rng.choices(alphabet, k=16))

    # --- API methods -------------------------------------------------------
    def get_users(self, logins: List[str] | None = None, ids: List[str] | None = None) -> Dict[str, Any]:
        results = list(self.users)
        if logins:
            wanted = {l.strip().lower() for l in logins}
            results = [u for u in results if u["login"].lower() in wanted]
        if ids:
            wanted_ids = {i.strip() for i in ids}
            results = [u for u in results if u["id"] in wanted_ids]
        return {"status": "ok", "output": results}

    def get_streams(self, user_logins: List[str] | None = None, user_ids: List[str] | None = None,
                    game_id: str | None = None) -> Dict[str, Any]:
        results = [s for s in self.streams if s["is_live"]]
        if user_logins:
            wanted = {l.strip().lower() for l in user_logins}
            results = [s for s in results if s["user_login"].lower() in wanted]
        if user_ids:
            wanted_ids = {i.strip() for i in user_ids}
            results = [s for s in results if s["user_id"] in wanted_ids]
        if game_id:
            results = [s for s in results if s["game_id"] == game_id]
        results.sort(key=lambda s: s["viewer_count"], reverse=True)
        return {"status": "ok", "output": results}

    def get_channels(self, broadcaster_ids: List[str]) -> Dict[str, Any]:
        wanted = {i.strip() for i in broadcaster_ids}
        results = [c for c in self.channels if c["broadcaster_id"] in wanted]
        return {"status": "ok", "output": results}

    def get_channel_followers(self, broadcaster_id: str) -> Dict[str, Any]:
        channel = next((c for c in self.channels if c["broadcaster_id"] == broadcaster_id), None)
        if not channel:
            return {"status": "ok", "output": {"data": [], "total": 0}}
        return {"status": "ok", "output": {"data": [], "total": channel["follower_count"]}}

    def get_top_games(self, first: int = 20) -> Dict[str, Any]:
        results = sorted(self.games, key=lambda g: g["rank"])[:first]
        return {"status": "ok", "output": results}

    def get_games(self, names: List[str] | None = None, ids: List[str] | None = None) -> Dict[str, Any]:
        results = list(self.games)
        if names:
            wanted = {n.strip().lower() for n in names}
            results = [g for g in results if g["name"].lower() in wanted]
        if ids:
            wanted_ids = {i.strip() for i in ids}
            results = [g for g in results if g["id"] in wanted_ids]
        return {"status": "ok", "output": results}

    def get_clips(self, broadcaster_id: str | None = None, game_id: str | None = None,
                  first: int = 20) -> Dict[str, Any]:
        results = list(self.clips)
        if broadcaster_id:
            results = [c for c in results if c["broadcaster_id"] == broadcaster_id]
        if game_id:
            results = [c for c in results if c["game_id"] == game_id]
        results.sort(key=lambda c: c["view_count"], reverse=True)
        return {"status": "ok", "output": results[:first]}



    def follow_channel(self, broadcaster_id: str) -> Dict[str, Any]:
        if not hasattr(self, 'follows'):
            self.follows = set()
        channel = next((c for c in self.channels if c["broadcaster_id"] == broadcaster_id), None)
        if not channel:
            return {"status": "failed", "output": f"Channel {broadcaster_id} not found"}
        if broadcaster_id in self.follows:
            return {"status": "failed", "output": "Already following this channel"}
        self.follows.add(broadcaster_id)
        channel["follower_count"] = channel.get("follower_count", 0) + 1
        return {"status": "ok", "output": {"broadcaster_id": broadcaster_id, "followed_at": self._now()}}

    def update_channel_info(self, broadcaster_id: str, title: str | None = None, game_name: str | None = None) -> Dict[str, Any]:
        channel = next((c for c in self.channels if c["broadcaster_id"] == broadcaster_id), None)
        if not channel:
            return {"status": "failed", "output": f"Channel {broadcaster_id} not found"}
        if title is not None:
            channel["title"] = title
        if game_name is not None:
            channel["game_name"] = game_name
        return {"status": "ok", "output": channel}

    def unfollow_channel(self, broadcaster_id: str) -> Dict[str, Any]:
        if not hasattr(self, 'follows'):
            self.follows = set()
        if broadcaster_id not in self.follows:
            return {"status": "failed", "output": "Not following this channel"}
        self.follows.discard(broadcaster_id)
        channel = next((c for c in self.channels if c["broadcaster_id"] == broadcaster_id), None)
        if channel and channel.get("follower_count", 0) > 0:
            channel["follower_count"] -= 1
        return {"status": "ok", "output": {"broadcaster_id": broadcaster_id, "unfollowed": True}}

if __name__ == "__main__":
    s = TwitchSession(seed=12)
    print(s.get_top_games())
    print(s.get_users(logins=["pixelpaladin"]))
