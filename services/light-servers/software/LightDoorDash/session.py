from shortuuid import uuid
from typing import Dict

try:
    from doordash import DoordashSession
except ImportError:
    from software.LightDoorDash.doordash import DoordashSession


class LightDoorDashSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.doordash_session = DoordashSession(os_cfg=os_cfg, seed=seed)
