from shortuuid import uuid
from typing import Dict
try:
    from notes import NotesSession
except ImportError:
    from software.LightNotes.notes import NotesSession

class LightNotesSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.notes_session = NotesSession(os_cfg=os_cfg, seed=seed)
