from shortuuid import uuid
from typing import Dict
try:                                             # app-runtime: own dir on sys.path
    from calendar_data import CalendarSession
except ImportError:                              # in-process grader: package import
    from software.LightCalendar.calendar_data import CalendarSession

class LightCalendarSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.calendar_session = CalendarSession(os_cfg=os_cfg, seed=seed)
