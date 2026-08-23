from shortuuid import uuid
from typing import Dict
try:
    from forum import ForumSession
except ImportError:
    from software.LightForum.forum import ForumSession

class LightForumSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.forum_session = ForumSession(os_cfg=os_cfg, seed=seed)
