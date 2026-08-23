from shortuuid import uuid
from typing import Dict
try:
    from auction import AuctionSession
except ImportError:
    from software.LightAuction.auction import AuctionSession

class LightAuctionSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.auction_session = AuctionSession(os_cfg=os_cfg, seed=seed)
