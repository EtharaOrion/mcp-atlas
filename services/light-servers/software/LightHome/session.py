from shortuuid import uuid
from typing import Dict
try:
    from home import HomeSession
except ImportError:
    from software.LightHome.home import HomeSession

class LightHomeSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.home_session = HomeSession(os_cfg=os_cfg, seed=seed)
