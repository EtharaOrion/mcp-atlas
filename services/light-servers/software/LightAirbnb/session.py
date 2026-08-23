from shortuuid import uuid
from typing import Dict

try:
    from airbnb import AirbnbSession
except ImportError:
    from software.LightAirbnb.airbnb import AirbnbSession


class LightAirbnbSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.airbnb_session = AirbnbSession(os_cfg=os_cfg, seed=seed)
