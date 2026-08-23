from shortuuid import uuid
from typing import Dict

try:
    from salesforce import SalesforceSession
except ImportError:
    from software.LightSalesforce.salesforce import SalesforceSession


class LightSalesforceSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.salesforce_session = SalesforceSession(os_cfg=os_cfg, seed=seed)
