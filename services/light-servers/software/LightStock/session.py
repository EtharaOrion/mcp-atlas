from shortuuid import uuid
from typing import Dict

try:
    from stock import StockSession
except ImportError:
    from software.LightStock.stock import StockSession


class LightStockSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.stock_session = StockSession(os_cfg=os_cfg, seed=seed)
