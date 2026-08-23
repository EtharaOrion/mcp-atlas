from shortuuid import uuid
from typing import Dict

try:
    from greenhouse import GreenhouseSession
except ImportError:
    from software.LightGreenhouse.greenhouse import GreenhouseSession


class LightGreenhouseSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.greenhouse_session = GreenhouseSession(os_cfg=os_cfg, seed=seed)
