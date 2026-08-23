from shortuuid import uuid
from typing import Dict

try:
    from reddit import RedditSession
except ImportError:
    from software.LightReddit.reddit import RedditSession


class LightRedditSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.reddit_session = RedditSession(os_cfg=os_cfg, seed=seed)
