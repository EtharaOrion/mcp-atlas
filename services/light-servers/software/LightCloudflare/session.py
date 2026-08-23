from shortuuid import uuid
from typing import Dict

try:
    from cloudflare import CloudflareSession
except ImportError:
    from software.LightCloudflare.cloudflare import CloudflareSession


class LightCloudflareSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.cloudflare_session = CloudflareSession(os_cfg=os_cfg, seed=seed)
