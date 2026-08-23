from shortuuid import uuid
from typing import Dict

try:
    from amplitude import AmplitudeSession
except ImportError:
    from software.LightAmplitude.amplitude import AmplitudeSession


class LightAmplitudeSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.amplitude_session = AmplitudeSession(os_cfg=os_cfg, seed=seed)
