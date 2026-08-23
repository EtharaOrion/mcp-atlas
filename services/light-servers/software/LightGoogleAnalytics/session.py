from shortuuid import uuid
from typing import Dict

try:
    from google_analytics import GoogleAnalyticsSession
except ImportError:
    from software.LightGoogleAnalytics.google_analytics import GoogleAnalyticsSession


class LightGoogleAnalyticsSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.google_analytics_session = GoogleAnalyticsSession(os_cfg=os_cfg, seed=seed)
