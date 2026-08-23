from shortuuid import uuid
from typing import Dict

try:
    from eventbrite import EventbriteSession
except ImportError:
    from software.LightEventbrite.eventbrite import EventbriteSession


class LightEventbriteSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.eventbrite_session = EventbriteSession(os_cfg=os_cfg, seed=seed)
