from shortuuid import uuid
from typing import Dict

try:
    from coinbase import CoinbaseSession
except ImportError:
    from software.LightCoinbase.coinbase import CoinbaseSession


class LightCoinbaseSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.coinbase_session = CoinbaseSession(os_cfg=os_cfg, seed=seed)
