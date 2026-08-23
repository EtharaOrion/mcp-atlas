from shortuuid import uuid
from typing import Dict

try:
    from pagerduty import PagerDutySession
except ImportError:
    from software.LightPagerDuty.pagerduty import PagerDutySession


class LightPagerDutySession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.pagerduty_session = PagerDutySession(os_cfg=os_cfg, seed=seed)
