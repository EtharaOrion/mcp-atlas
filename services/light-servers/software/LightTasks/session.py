from shortuuid import uuid
from typing import Dict
try:
    from tasks import TasksSession
except ImportError:
    from software.LightTasks.tasks import TasksSession

class LightTasksSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.tasks_session = TasksSession(os_cfg=os_cfg, seed=seed)
