from shortuuid import uuid
from typing import Dict

try:
    from kraken import KrakenSession
except ImportError:
    from software.LightKraken.kraken import KrakenSession


class LightKrakenSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.kraken_session = KrakenSession(os_cfg=os_cfg, seed=seed)
