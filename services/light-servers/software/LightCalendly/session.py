from shortuuid import uuid
from typing import Dict

try:
    from calendly import CalendlySession
except ImportError:
    from software.LightCalendly.calendly import CalendlySession


class LightCalendlySession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.calendly_session = CalendlySession(os_cfg=os_cfg, seed=seed)
