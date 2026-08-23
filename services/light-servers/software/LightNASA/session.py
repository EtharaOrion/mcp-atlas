from shortuuid import uuid
from typing import Dict

try:
    from nasa import NasaSession
except ImportError:
    from software.LightNASA.nasa import NasaSession


class LightNASASession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.nasa_session = NasaSession(os_cfg=os_cfg, seed=seed)
