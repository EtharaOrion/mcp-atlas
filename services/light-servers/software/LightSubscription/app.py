from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightSubscriptionSession
except ImportError:
    from software.LightSubscription.session import LightSubscriptionSession
import logging, colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightSubscription")
session_dict: Dict[str, LightSubscriptionSession] = {}

def get_session(session_id: str):
    s = session_dict.get(session_id)
    if s is None: return None, {"status": "failed", "output": "session not found"}
    return s, None

@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    s = LightSubscriptionSession(os_cfg=os_cfg, seed=seed)
    session_dict[s.session_id] = s
    return {"status": "ok", "session_id": s.session_id, "session_info": {"status": "ok", "output": s.subscription_session.get_session_dict()}}

@mcp.tool
async def logout(session_id: str):
    s, err = get_session(session_id)
    if err: return err
    info = {"status": "ok", "output": s.subscription_session.get_session_dict()}
    del session_dict[session_id]
    return info

@mcp.tool
async def list_subscriptions(session_id: str, status: Optional[str] = None, category: Optional[str] = None):
    s, err = get_session(session_id)
    if err: return err
    return s.subscription_session.list_subscriptions(status=status, category=category)

@mcp.tool
async def get_subscription(sid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.subscription_session.get_subscription(sid)

@mcp.tool
async def add_subscription(name: str, provider: str, amount: float, session_id: str, period: str = "monthly", currency: str = "USD", next_charge: str = "", category: str = "general"):
    s, err = get_session(session_id)
    if err: return err
    return s.subscription_session.add_subscription(name, provider, amount, period, currency, next_charge, category)

@mcp.tool
async def update_subscription(sid: str, session_id: str, name: Optional[str] = None, provider: Optional[str] = None, amount: Optional[float] = None, period: Optional[str] = None, currency: Optional[str] = None, next_charge: Optional[str] = None, category: Optional[str] = None):
    s, err = get_session(session_id)
    if err: return err
    return s.subscription_session.update_subscription(sid, name=name, provider=provider, amount=amount, period=period, currency=currency, next_charge=next_charge, category=category)

@mcp.tool
async def cancel_subscription(sid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.subscription_session.cancel_subscription(sid)

@mcp.tool
async def pause_subscription(sid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.subscription_session.pause_subscription(sid)

@mcp.tool
async def resume_subscription(sid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.subscription_session.resume_subscription(sid)

@mcp.tool
async def delete_subscription(sid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.subscription_session.delete_subscription(sid)

@mcp.tool
async def record_payment(subscription_id: str, amount: float, date: str, session_id: str, currency: str = "USD", status: str = "paid"):
    s, err = get_session(session_id)
    if err: return err
    return s.subscription_session.record_payment(subscription_id, amount, date, currency, status)

@mcp.tool
async def list_payments(session_id: str, subscription_id: Optional[str] = None, status: Optional[str] = None):
    s, err = get_session(session_id)
    if err: return err
    return s.subscription_session.list_payments(subscription_id, status)

@mcp.tool
async def monthly_cost(session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.subscription_session.monthly_cost()

@mcp.tool
async def yearly_cost(session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.subscription_session.yearly_cost()

@mcp.tool
async def cost_by_category(session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.subscription_session.cost_by_category()

@mcp.tool
async def upcoming_charges(session_id: str, limit: int = 5):
    s, err = get_session(session_id)
    if err: return err
    return s.subscription_session.upcoming_charges(limit=limit)

@mcp.tool
async def search(query: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.subscription_session.search(query)

@mcp.tool
async def get_stats(session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.subscription_session.get_stats()
