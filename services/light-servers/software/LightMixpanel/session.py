from shortuuid import uuid
from typing import Dict

try:
    from mixpanel import MixpanelSession
except ImportError:
    from software.LightMixpanel.mixpanel import MixpanelSession


class LightMixpanelSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.mixpanel_session = MixpanelSession(os_cfg=os_cfg, seed=seed)
