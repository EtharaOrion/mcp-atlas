from shortuuid import uuid
from typing import Dict

try:
    from bigcommerce import BigcommerceSession
except ImportError:
    from software.LightBigCommerce.bigcommerce import BigcommerceSession


class LightBigCommerceSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.bigcommerce_session = BigcommerceSession(os_cfg=os_cfg, seed=seed)
