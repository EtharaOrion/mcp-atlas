from shortuuid import uuid
from typing import Dict

try:
    from zendesk import ZendeskSession
except ImportError:
    from software.LightZendesk.zendesk import ZendeskSession


class LightZendeskSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.zendesk_session = ZendeskSession(os_cfg=os_cfg, seed=seed)
