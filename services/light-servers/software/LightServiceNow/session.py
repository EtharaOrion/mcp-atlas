from shortuuid import uuid
from typing import Dict

try:
    from servicenow import ServicenowSession
except ImportError:
    from software.LightServiceNow.servicenow import ServicenowSession


class LightServiceNowSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.servicenow_session = ServicenowSession(os_cfg=os_cfg, seed=seed)
