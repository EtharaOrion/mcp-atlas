from shortuuid import uuid
from typing import Dict

try:
    from etsy import EtsySession
except ImportError:
    from software.LightEtsy.etsy import EtsySession


class LightEtsySession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.etsy_session = EtsySession(os_cfg=os_cfg, seed=seed)
