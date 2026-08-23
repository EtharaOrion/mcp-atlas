from shortuuid import uuid
from typing import Dict
try:
    from med import MedSession
except ImportError:
    from software.LightMed.med import MedSession

class LightMedSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.med_session = MedSession(os_cfg=os_cfg, seed=seed)
