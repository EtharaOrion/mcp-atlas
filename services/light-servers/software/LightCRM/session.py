from shortuuid import uuid
from typing import Dict
try:
    from crm import CRMSession
except ImportError:
    from software.LightCRM.crm import CRMSession

class LightCRMSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.crm_session = CRMSession(os_cfg=os_cfg, seed=seed)
