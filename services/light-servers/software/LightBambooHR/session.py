from shortuuid import uuid
from typing import Dict

try:
    from bamboohr import BamboohrSession
except ImportError:
    from software.LightBambooHR.bamboohr import BamboohrSession


class LightBambooHRSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.bamboohr_session = BamboohrSession(os_cfg=os_cfg, seed=seed)
