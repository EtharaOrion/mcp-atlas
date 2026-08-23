from shortuuid import uuid
from typing import Dict
try:
    from news import NewsSession
except ImportError:
    from software.LightNews.news import NewsSession

class LightNewsSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.news_session = NewsSession(os_cfg=os_cfg, seed=seed)

    
    