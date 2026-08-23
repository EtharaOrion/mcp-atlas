from shortuuid import uuid
from typing import Dict

try:
    from contentful import ContentfulSession
except ImportError:
    from software.LightContentful.contentful import ContentfulSession


class LightContentfulSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.contentful_session = ContentfulSession(os_cfg=os_cfg, seed=seed)
