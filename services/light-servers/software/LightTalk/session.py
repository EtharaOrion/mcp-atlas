from shortuuid import uuid
from typing import Dict
try:
    from contact import ContactSession
except ImportError:
    from software.LightTalk.contact import ContactSession

from software.utils.core import OSConnector

class LightTalkSession:
    def __init__(
        self,
        os_cfg: Dict[str, str],
        seed: int | None = None,
        fixture: str | None = None
    ):
        # Seedless: `seed` is accepted for backward-compat with the client's
        # login call and ignored — the world is loaded from a static fixture.
        self.session_id = f"session_{uuid()}"
        self.contact_session = ContactSession(os_cfg=os_cfg, seed=seed, fixture=fixture)
    
    
