from shortuuid import uuid
from typing import Dict
try:
    from photo import PhotoSession
except ImportError:
    from software.LightPhoto.photo import PhotoSession

class LightPhotoSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.photo_session = PhotoSession(os_cfg=os_cfg, seed=seed)
