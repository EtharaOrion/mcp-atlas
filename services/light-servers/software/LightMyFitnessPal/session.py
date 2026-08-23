from shortuuid import uuid
from typing import Dict

try:
    from myfitnesspal import MyfitnesspalSession
except ImportError:
    from software.LightMyFitnessPal.myfitnesspal import MyfitnesspalSession


class LightMyFitnessPalSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.myfitnesspal_session = MyfitnesspalSession(os_cfg=os_cfg, seed=seed)
