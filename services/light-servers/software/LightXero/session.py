from shortuuid import uuid
from typing import Dict

try:
    from xero import XeroSession
except ImportError:
    from software.LightXero.xero import XeroSession


class LightXeroSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.xero_session = XeroSession(os_cfg=os_cfg, seed=seed)
