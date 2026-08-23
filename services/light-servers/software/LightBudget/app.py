from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightBudgetSession
except ImportError:
    from software.LightBudget.session import LightBudgetSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightBudget")

session_dict: Dict[str, LightBudgetSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None, fixture: str | None = None):
    session = LightBudgetSession(os_cfg=os_cfg, seed=seed, fixture=fixture)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.budget_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.budget_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_categories(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.budget_session.list_categories()


@mcp.tool
async def create_category(name: str, session_id: str,
                          color: str = "#888888", monthly_limit: float = 0.0):
    session, err = get_session(session_id)
    if err: return err
    return session.budget_session.create_category(
        name=name, color=color, monthly_limit=monthly_limit
    )


@mcp.tool
async def delete_category(catid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.budget_session.delete_category(catid)


@mcp.tool
async def update_category(catid: str, session_id: str,
                          name: Optional[str] = None,
                          color: Optional[str] = None,
                          monthly_limit: Optional[float] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.budget_session.update_category(
        catid=catid, name=name, color=color, monthly_limit=monthly_limit
    )


@mcp.tool
async def list_transactions(session_id: str,
                            category_id: Optional[str] = None,
                            kind: Optional[str] = None,
                            start_date: Optional[str] = None,
                            end_date: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.budget_session.list_transactions(
        category_id=category_id, kind=kind,
        start_date=start_date, end_date=end_date,
    )


@mcp.tool
async def get_transaction(txid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.budget_session.get_transaction(txid)


@mcp.tool
async def create_transaction(category_id: str, amount: float, date: str, session_id: str,
                             description: str = "", currency: str = "USD",
                             kind: str = "expense"):
    session, err = get_session(session_id)
    if err: return err
    return session.budget_session.create_transaction(
        category_id=category_id, amount=amount, date=date,
        description=description, currency=currency, kind=kind,
    )


@mcp.tool
async def update_transaction(txid: str, session_id: str,
                             category_id: Optional[str] = None,
                             amount: Optional[float] = None,
                             date: Optional[str] = None,
                             description: Optional[str] = None,
                             currency: Optional[str] = None,
                             kind: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.budget_session.update_transaction(
        txid=txid, category_id=category_id, amount=amount, date=date,
        description=description, currency=currency, kind=kind,
    )


@mcp.tool
async def delete_transaction(txid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.budget_session.delete_transaction(txid)


@mcp.tool
async def list_budgets(session_id: str, month: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.budget_session.list_budgets(month=month)


@mcp.tool
async def get_budget(bid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.budget_session.get_budget(bid)


@mcp.tool
async def set_budget(month: str, category_id: str, limit: float, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.budget_session.set_budget(
        month=month, category_id=category_id, limit=limit
    )


@mcp.tool
async def get_spending_by_category(month: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.budget_session.get_spending_by_category(month=month)


@mcp.tool
async def get_monthly_summary(month: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.budget_session.get_monthly_summary(month=month)


@mcp.tool
async def search_transactions(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.budget_session.search_transactions(query)


@mcp.tool
async def get_savings_rate(month: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.budget_session.get_savings_rate(month=month)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.budget_session.get_stats()
