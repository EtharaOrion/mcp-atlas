from shortuuid import uuid
from typing import Dict
try:
    from subscription import SubscriptionSession
except ImportError:
    from software.LightSubscription.subscription import SubscriptionSession

class LightSubscriptionSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.subscription_session = SubscriptionSession(os_cfg=os_cfg, seed=seed)
