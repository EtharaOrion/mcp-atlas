from shortuuid import uuid
from typing import Dict

try:
    from dropbox import DropboxSession
except ImportError:
    from software.LightDropbox.dropbox import DropboxSession


class LightDropboxSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.dropbox_session = DropboxSession(os_cfg=os_cfg, seed=seed)
