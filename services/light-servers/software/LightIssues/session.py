from shortuuid import uuid
from typing import Dict
try:
    from issues import IssuesSession
except ImportError:
    from software.LightIssues.issues import IssuesSession

class LightIssuesSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.issues_session = IssuesSession(os_cfg=os_cfg, seed=seed)
