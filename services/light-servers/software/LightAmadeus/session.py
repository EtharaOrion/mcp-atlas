from shortuuid import uuid
from typing import Dict

try:
    from amadeus import AmadeusSession
except ImportError:
    from software.LightAmadeus.amadeus import AmadeusSession


class LightAmadeusSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.amadeus_session = AmadeusSession(os_cfg=os_cfg, seed=seed)
