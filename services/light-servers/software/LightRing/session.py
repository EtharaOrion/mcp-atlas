from shortuuid import uuid
from typing import Dict

try:
    from ring import RingSession
except ImportError:
    from software.LightRing.ring import RingSession


class LightRingSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.ring_session = RingSession(os_cfg=os_cfg, seed=seed)
