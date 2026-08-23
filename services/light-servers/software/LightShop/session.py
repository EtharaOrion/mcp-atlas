from shortuuid import uuid

# import sys
# from pathlib import Path

# WORK_DIR = Path(".").__str__()

# if WORK_DIR not in sys.path:
#     sys.path.append(WORK_DIR)

try:
    from shop import ShopSession
except ImportError:
    from software.LightShop.shop import ShopSession
from typing import Dict

class LightShopSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None, fixture=None):
        self.session_id = f"session_{uuid()}"
        self.shop_session = ShopSession(os_cfg=os_cfg, seed=seed, fixture=fixture)