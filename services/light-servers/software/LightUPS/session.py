from shortuuid import uuid
from typing import Dict

try:
    from ups import UpsSession
except ImportError:
    from software.LightUPS.ups import UpsSession


class LightUPSSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.ups_session = UpsSession(os_cfg=os_cfg, seed=seed)
