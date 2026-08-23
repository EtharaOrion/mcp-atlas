from shortuuid import uuid
from typing import Dict

try:
    from mailgun import MailgunSession
except ImportError:
    from software.LightMailgun.mailgun import MailgunSession


class LightMailgunSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.mailgun_session = MailgunSession(os_cfg=os_cfg, seed=seed)
