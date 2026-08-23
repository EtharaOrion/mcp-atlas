from shortuuid import uuid
from typing import Dict

try:
    from confluence import ConfluenceSession
except ImportError:
    from software.LightConfluence.confluence import ConfluenceSession


class LightConfluenceSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.confluence_session = ConfluenceSession(os_cfg=os_cfg, seed=seed)
