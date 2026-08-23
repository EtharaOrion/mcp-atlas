from shortuuid import uuid
from typing import Dict
try:
    from mail import MailSession
except ImportError:
    from software.LightMail.mail import MailSession

class LightMailSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.mail_session = MailSession(os_cfg=os_cfg, seed=seed)
