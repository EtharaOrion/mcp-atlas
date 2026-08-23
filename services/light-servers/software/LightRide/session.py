from shortuuid import uuid
from typing import Dict
try:
    from ride import RideSession
except ImportError:
    from software.LightRide.ride import RideSession

class LightRideSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.ride_session = RideSession(os_cfg=os_cfg, seed=seed)
