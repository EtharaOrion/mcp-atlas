from shortuuid import uuid
from typing import Dict
try:
    from read import ReadSession
except ImportError:
    from software.LightRead.read import ReadSession

class LightReadSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.read_session = ReadSession(os_cfg=os_cfg, seed=seed)
