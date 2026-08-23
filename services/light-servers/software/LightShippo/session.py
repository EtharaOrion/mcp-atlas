from shortuuid import uuid
from typing import Dict

try:
    from shippo import ShippoSession
except ImportError:
    from software.LightShippo.shippo import ShippoSession


class LightShippoSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.shippo_session = ShippoSession(os_cfg=os_cfg, seed=seed)
