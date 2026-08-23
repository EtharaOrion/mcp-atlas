from shortuuid import uuid
from typing import Dict
try:
    from hotel import HotelSession
except ImportError:
    from software.LightHotel.hotel import HotelSession

class LightHotelSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.hotel_session = HotelSession(os_cfg=os_cfg, seed=seed)
