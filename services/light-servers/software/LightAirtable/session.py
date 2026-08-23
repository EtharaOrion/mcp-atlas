from shortuuid import uuid
from typing import Dict

try:
    from airtable import AirtableSession
except ImportError:
    from software.LightAirtable.airtable import AirtableSession


class LightAirtableSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.airtable_session = AirtableSession(os_cfg=os_cfg, seed=seed)
