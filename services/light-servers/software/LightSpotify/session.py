from shortuuid import uuid
from typing import Dict

try:
    from spotify import SpotifySession
except ImportError:
    from software.LightSpotify.spotify import SpotifySession


class LightSpotifySession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.spotify_session = SpotifySession(os_cfg=os_cfg, seed=seed)
