from shortuuid import uuid
from typing import Dict

try:
    from zoom import ZoomSession
except ImportError:
    from software.LightZoom.zoom import ZoomSession


class LightZoomSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.zoom_session = ZoomSession(os_cfg=os_cfg, seed=seed)
