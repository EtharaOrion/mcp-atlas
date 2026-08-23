from shortuuid import uuid
from typing import Dict

try:
    from sendgrid import SendgridSession
except ImportError:
    from software.LightSendGrid.sendgrid import SendgridSession


class LightSendGridSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.sendgrid_session = SendgridSession(os_cfg=os_cfg, seed=seed)
