from shortuuid import uuid
from typing import Dict

try:
    from microsoft_teams import MicrosoftTeamsSession
except ImportError:
    from software.LightMicrosoftTeams.microsoft_teams import MicrosoftTeamsSession


class LightMicrosoftTeamsSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.microsoft_teams_session = MicrosoftTeamsSession(os_cfg=os_cfg, seed=seed)
