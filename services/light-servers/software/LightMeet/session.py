from shortuuid import uuid
from typing import Dict
try:
    from meet import MeetSession
except ImportError:
    from software.LightMeet.meet import MeetSession

class LightMeetSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.meet_session = MeetSession(os_cfg=os_cfg, seed=seed)
