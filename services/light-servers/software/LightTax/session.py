from shortuuid import uuid
from typing import Dict
try:
    from tax import TaxSession
except ImportError:
    from software.LightTax.tax import TaxSession

class LightTaxSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.tax_session = TaxSession(os_cfg=os_cfg, seed=seed)
