from shortuuid import uuid
from typing import Dict
try:
    from security import SecuritySession
except ImportError:
    from software.LightSecurity.security import SecuritySession

class LightSecuritySession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.security_session = SecuritySession(os_cfg=os_cfg, seed=seed)
