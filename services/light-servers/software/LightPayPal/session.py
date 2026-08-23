from shortuuid import uuid
from typing import Dict

try:
    from paypal import PaypalSession
except ImportError:
    from software.LightPayPal.paypal import PaypalSession


class LightPayPalSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.paypal_session = PaypalSession(os_cfg=os_cfg, seed=seed)
