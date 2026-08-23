from shortuuid import uuid
from typing import Dict

try:
    from yelp import YelpSession
except ImportError:
    from software.LightYelp.yelp import YelpSession


class LightYelpSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.yelp_session = YelpSession(os_cfg=os_cfg, seed=seed)
