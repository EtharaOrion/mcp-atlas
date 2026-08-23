from shortuuid import uuid
from typing import Dict

try:
    from youtube import YoutubeSession
except ImportError:
    from software.LightYouTube.youtube import YoutubeSession


class LightYouTubeSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.youtube_session = YoutubeSession(os_cfg=os_cfg, seed=seed)
