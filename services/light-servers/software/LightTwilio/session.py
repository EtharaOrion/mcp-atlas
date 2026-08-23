from shortuuid import uuid
from typing import Dict

try:
    from twilio import TwilioSession
except ImportError:
    from software.LightTwilio.twilio import TwilioSession


class LightTwilioSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.twilio_session = TwilioSession(os_cfg=os_cfg, seed=seed)
