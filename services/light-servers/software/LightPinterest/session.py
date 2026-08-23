from shortuuid import uuid
from typing import Dict

try:
    from pinterest import PinterestSession
except ImportError:
    from software.LightPinterest.pinterest import PinterestSession


class LightPinterestSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.pinterest_session = PinterestSession(os_cfg=os_cfg, seed=seed)
