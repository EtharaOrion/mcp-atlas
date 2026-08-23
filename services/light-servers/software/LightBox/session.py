from shortuuid import uuid
from typing import Dict

try:
    from box import BoxSession
except ImportError:
    from software.LightBox.box import BoxSession


class LightBoxSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.box_session = BoxSession(os_cfg=os_cfg, seed=seed)
