from shortuuid import uuid
from typing import Dict

try:
    from google_maps import GoogleMapsSession
except ImportError:
    from software.LightGoogleMaps.google_maps import GoogleMapsSession


class LightGoogleMapsSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.google_maps_session = GoogleMapsSession(os_cfg=os_cfg, seed=seed)
