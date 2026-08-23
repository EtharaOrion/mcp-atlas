from shortuuid import uuid
from typing import Dict

try:
    from obsidian import ObsidianSession
except ImportError:
    from software.LightObsidian.obsidian import ObsidianSession


class LightObsidianSession:
    def __init__(self, os_cfg: Dict[str, str], seed=None):
        self.session_id = f"session_{uuid()}"
        self.obsidian_session = ObsidianSession(os_cfg=os_cfg, seed=seed)
