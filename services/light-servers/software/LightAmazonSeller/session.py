from shortuuid import uuid
from typing import Dict

try:
    from amazon_seller import AmazonSellerSession
except ImportError:
    from software.LightAmazonSeller.amazon_seller import AmazonSellerSession


class LightAmazonSellerSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.amazon_seller_session = AmazonSellerSession(os_cfg=os_cfg, seed=seed)
