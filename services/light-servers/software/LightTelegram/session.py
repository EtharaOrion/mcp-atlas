from shortuuid import uuid
from typing import Dict

try:
    from telegram import TelegramSession
except ImportError:
    from software.LightTelegram.telegram import TelegramSession


class LightTelegramSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.telegram_session = TelegramSession(os_cfg=os_cfg, seed=seed)
