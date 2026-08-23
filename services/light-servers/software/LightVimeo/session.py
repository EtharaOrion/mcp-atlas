from shortuuid import uuid
from typing import Dict

try:
    from vimeo import VimeoSession
except ImportError:
    from software.LightVimeo.vimeo import VimeoSession


class LightVimeoSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.vimeo_session = VimeoSession(os_cfg=os_cfg, seed=seed)
