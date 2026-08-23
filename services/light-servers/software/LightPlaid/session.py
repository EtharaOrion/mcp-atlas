from shortuuid import uuid
from typing import Dict

try:
    from plaid import PlaidSession
except ImportError:
    from software.LightPlaid.plaid import PlaidSession


class LightPlaidSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.plaid_session = PlaidSession(os_cfg=os_cfg, seed=seed)
