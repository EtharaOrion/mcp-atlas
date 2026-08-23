from shortuuid import uuid
from typing import Dict

try:
    from whatsapp import WhatsappSession
except ImportError:
    from software.LightWhatsApp.whatsapp import WhatsappSession


class LightWhatsAppSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None, fixture=None):
        self.session_id = f"session_{uuid()}"
        self.whatsapp_session = WhatsappSession(os_cfg=os_cfg, seed=seed, fixture=fixture)
