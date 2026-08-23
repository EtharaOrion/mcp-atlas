from shortuuid import uuid
from typing import Dict

try:
    from instacart import InstacartSession
except ImportError:
    from software.LightInstacart.instacart import InstacartSession


class LightInstacartSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.instacart_session = InstacartSession(os_cfg=os_cfg, seed=seed)
