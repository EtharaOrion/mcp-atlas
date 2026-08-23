from shortuuid import uuid
from typing import Dict

try:
    from mailchimp import MailchimpSession
except ImportError:
    from software.LightMailchimp.mailchimp import MailchimpSession


class LightMailchimpSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.mailchimp_session = MailchimpSession(os_cfg=os_cfg, seed=seed)
