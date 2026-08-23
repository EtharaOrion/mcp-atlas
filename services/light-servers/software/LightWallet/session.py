from shortuuid import uuid
from typing import Dict
try:
    from wallet import WalletSession
except ImportError:
    from software.LightWallet.wallet import WalletSession

class LightWalletSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.wallet_session = WalletSession(os_cfg=os_cfg, seed=seed)
