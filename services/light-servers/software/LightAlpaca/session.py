from shortuuid import uuid
from typing import Dict

try:
    from alpaca import AlpacaSession
except ImportError:
    from software.LightAlpaca.alpaca import AlpacaSession


class LightAlpacaSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.alpaca_session = AlpacaSession(os_cfg=os_cfg, seed=seed)
