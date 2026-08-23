from shortuuid import uuid
from typing import Dict

try:
    from monday import MondaySession
except ImportError:
    from software.LightMonday.monday import MondaySession


class LightMondaySession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.monday_session = MondaySession(os_cfg=os_cfg, seed=seed)
