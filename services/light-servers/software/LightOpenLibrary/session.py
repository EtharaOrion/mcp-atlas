from shortuuid import uuid
from typing import Dict

try:
    from openlibrary import OpenlibrarySession
except ImportError:
    from software.LightOpenLibrary.openlibrary import OpenlibrarySession


class LightOpenLibrarySession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.openlibrary_session = OpenlibrarySession(os_cfg=os_cfg, seed=seed)
