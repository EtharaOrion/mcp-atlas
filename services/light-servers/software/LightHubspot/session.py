from shortuuid import uuid
from typing import Dict

try:
    from hubspot import HubspotSession
except ImportError:
    from software.LightHubspot.hubspot import HubspotSession


class LightHubspotSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.hubspot_session = HubspotSession(os_cfg=os_cfg, seed=seed)
