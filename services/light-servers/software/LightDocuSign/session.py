from shortuuid import uuid
from typing import Dict

try:
    from docusign import DocusignSession
except ImportError:
    from software.LightDocuSign.docusign import DocusignSession


class LightDocuSignSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.docusign_session = DocusignSession(os_cfg=os_cfg, seed=seed)
