from shortuuid import uuid
from typing import Dict

try:
    from activecampaign import ActiveCampaignSession
except ImportError:
    from software.LightActiveCampaign.activecampaign import ActiveCampaignSession


class LightActiveCampaignSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.activecampaign_session = ActiveCampaignSession(os_cfg=os_cfg, seed=seed)
