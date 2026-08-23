from shortuuid import uuid
from typing import Dict

try:
    from strava import StravaSession
except ImportError:
    from software.LightStrava.strava import StravaSession


class LightStravaSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.strava_session = StravaSession(os_cfg=os_cfg, seed=seed)
