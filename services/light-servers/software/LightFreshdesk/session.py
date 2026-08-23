from shortuuid import uuid
from typing import Dict

try:
    from freshdesk import FreshdeskSession
except ImportError:
    from software.LightFreshdesk.freshdesk import FreshdeskSession


class LightFreshdeskSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.freshdesk_session = FreshdeskSession(os_cfg=os_cfg, seed=seed)
