from shortuuid import uuid
from typing import Dict

try:
    from google_drive import GoogleDriveSession
except ImportError:
    from software.LightGoogleDrive.google_drive import GoogleDriveSession


class LightGoogleDriveSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.google_drive_session = GoogleDriveSession(os_cfg=os_cfg, seed=seed)
