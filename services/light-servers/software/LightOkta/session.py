from shortuuid import uuid
from typing import Dict

try:
    from okta import OktaSession
except ImportError:
    from software.LightOkta.okta import OktaSession


class LightOktaSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.okta_session = OktaSession(os_cfg=os_cfg, seed=seed)
