from shortuuid import uuid
from typing import Dict

try:
    from woocommerce import WoocommerceSession
except ImportError:
    from software.LightWooCommerce.woocommerce import WoocommerceSession


class LightWooCommerceSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.woocommerce_session = WoocommerceSession(os_cfg=os_cfg, seed=seed)
