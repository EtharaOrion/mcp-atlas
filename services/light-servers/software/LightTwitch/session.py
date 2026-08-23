from shortuuid import uuid
from typing import Dict

try:
    from twitch import TwitchSession
except ImportError:
    from software.LightTwitch.twitch import TwitchSession


class LightTwitchSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.twitch_session = TwitchSession(os_cfg=os_cfg, seed=seed)
