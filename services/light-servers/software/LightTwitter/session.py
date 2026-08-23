from shortuuid import uuid
from typing import Dict

try:
    from twitter import TwitterSession
except ImportError:
    from software.LightTwitter.twitter import TwitterSession


class LightTwitterSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.twitter_session = TwitterSession(os_cfg=os_cfg, seed=seed)
