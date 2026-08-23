from shortuuid import uuid
from typing import Dict

try:
    from trello import TrelloSession
except ImportError:
    from software.LightTrello.trello import TrelloSession


class LightTrelloSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.trello_session = TrelloSession(os_cfg=os_cfg, seed=seed)
