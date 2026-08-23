from shortuuid import uuid
from typing import Dict

try:
    from instagram import InstagramSession
except ImportError:
    from software.LightInstagram.instagram import InstagramSession


class LightInstagramSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.instagram_session = InstagramSession(os_cfg=os_cfg, seed=seed)
