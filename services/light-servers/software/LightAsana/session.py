from shortuuid import uuid
from typing import Dict

try:
    from asana import AsanaSession
except ImportError:
    from software.LightAsana.asana import AsanaSession


class LightAsanaSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.asana_session = AsanaSession(os_cfg=os_cfg, seed=seed)
