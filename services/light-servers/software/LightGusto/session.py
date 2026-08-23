from shortuuid import uuid
from typing import Dict

try:
    from gusto import GustoSession
except ImportError:
    from software.LightGusto.gusto import GustoSession


class LightGustoSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.gusto_session = GustoSession(os_cfg=os_cfg, seed=seed)
