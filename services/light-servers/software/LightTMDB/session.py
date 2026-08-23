from shortuuid import uuid
from typing import Dict

try:
    from tmdb import TmdbSession
except ImportError:
    from software.LightTMDB.tmdb import TmdbSession


class LightTMDBSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.tmdb_session = TmdbSession(os_cfg=os_cfg, seed=seed)
