from shortuuid import uuid
from typing import Dict

try:
    from klaviyo import KlaviyoSession
except ImportError:
    from software.LightKlaviyo.klaviyo import KlaviyoSession


class LightKlaviyoSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.klaviyo_session = KlaviyoSession(os_cfg=os_cfg, seed=seed)
