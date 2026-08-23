from shortuuid import uuid
from typing import Dict

try:
    from gitlab import GitlabSession
except ImportError:
    from software.LightGitlab.gitlab import GitlabSession


class LightGitlabSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.gitlab_session = GitlabSession(os_cfg=os_cfg, seed=seed)
