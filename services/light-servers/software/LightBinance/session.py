from shortuuid import uuid
from typing import Dict

try:
    from binance import BinanceSession
except ImportError:
    from software.LightBinance.binance import BinanceSession


class LightBinanceSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.binance_session = BinanceSession(os_cfg=os_cfg, seed=seed)
