from shortuuid import uuid
from typing import Dict

try:
    from slack import SlackSession
except ImportError:
    from software.LightSlack.slack import SlackSession


class LightSlackSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.slack_session = SlackSession(os_cfg=os_cfg, seed=seed)
