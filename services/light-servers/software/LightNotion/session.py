from shortuuid import uuid
from typing import Dict

try:
    from notion import NotionSession
except ImportError:
    from software.LightNotion.notion import NotionSession


class LightNotionSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.notion_session = NotionSession(os_cfg=os_cfg, seed=seed)
