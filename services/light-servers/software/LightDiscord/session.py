from shortuuid import uuid
from typing import Dict

try:
    from discord import DiscordSession
except ImportError:
    from software.LightDiscord.discord import DiscordSession


class LightDiscordSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.discord_session = DiscordSession(os_cfg=os_cfg, seed=seed)
