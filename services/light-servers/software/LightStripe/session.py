from shortuuid import uuid
from typing import Dict

try:
    from stripe import StripeSession
except ImportError:
    from software.LightStripe.stripe import StripeSession


class LightStripeSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.stripe_session = StripeSession(os_cfg=os_cfg, seed=seed)
