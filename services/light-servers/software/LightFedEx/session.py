from shortuuid import uuid
from typing import Dict

try:
    from fedex import FedexSession
except ImportError:
    from software.LightFedEx.fedex import FedexSession


class LightFedExSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.fedex_session = FedexSession(os_cfg=os_cfg, seed=seed)
