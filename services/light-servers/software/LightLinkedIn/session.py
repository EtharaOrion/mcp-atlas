from shortuuid import uuid
from typing import Dict

try:
    from linkedin import LinkedinSession
except ImportError:
    from software.LightLinkedIn.linkedin import LinkedinSession


class LightLinkedInSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.linkedin_session = LinkedinSession(os_cfg=os_cfg, seed=seed)
