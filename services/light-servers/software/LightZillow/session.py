from shortuuid import uuid
from typing import Dict

try:
    from zillow import ZillowSession
except ImportError:
    from software.LightZillow.zillow import ZillowSession


class LightZillowSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.zillow_session = ZillowSession(os_cfg=os_cfg, seed=seed)
