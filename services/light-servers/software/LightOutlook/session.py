from shortuuid import uuid
from typing import Dict

try:
    from outlook import OutlookSession
except ImportError:
    from software.LightOutlook.outlook import OutlookSession


class LightOutlookSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.outlook_session = OutlookSession(os_cfg=os_cfg, seed=seed)
