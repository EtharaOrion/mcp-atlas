from shortuuid import uuid
from typing import Dict

try:
    from jira import JiraSession
except ImportError:
    from software.LightJira.jira import JiraSession


class LightJiraSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.jira_session = JiraSession(os_cfg=os_cfg, seed=seed)
