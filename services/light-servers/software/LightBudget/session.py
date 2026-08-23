from shortuuid import uuid
from typing import Dict
try:
    from budget import BudgetSession
except ImportError:
    from software.LightBudget.budget import BudgetSession

class LightBudgetSession:
    def __init__(self, os_cfg: Dict[str, str]
    , seed=None, fixture=None):
        self.session_id = f"session_{uuid()}"
        self.budget_session = BudgetSession(os_cfg=os_cfg, seed=seed, fixture=fixture)
