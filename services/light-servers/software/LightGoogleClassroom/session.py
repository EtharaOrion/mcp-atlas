from shortuuid import uuid
from typing import Dict

try:
    from google_classroom import GoogleClassroomSession
except ImportError:
    from software.LightGoogleClassroom.google_classroom import GoogleClassroomSession


class LightGoogleClassroomSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.google_classroom_session = GoogleClassroomSession(os_cfg=os_cfg, seed=seed)
