from shortuuid import uuid
from typing import Dict
try:
    from food import FoodSession
except ImportError:
    from software.LightFood.food import FoodSession

class LightFoodSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None):
        self.session_id = f"session_{uuid()}"
        self.food_session = FoodSession(os_cfg=os_cfg, seed=seed)
