from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightWalletSession
except ImportError:
    from software.LightWallet.session import LightWalletSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightWallet")

session_dict: Dict[str, LightWalletSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightWalletSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.wallet_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.wallet_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_wallets(session_id: str, kind: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.wallet_session.list_wallets(kind=kind)


@mcp.tool
async def get_wallet(wid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.wallet_session.get_wallet(wid)


@mcp.tool
async def create_wallet(name: str, currency: str, session_id: str,
                        kind: str = "fiat", balance: float = 0.0):
    session, err = get_session(session_id)
    if err: return err
    return session.wallet_session.create_wallet(
        name=name, currency=currency, kind=kind, balance=balance
    )


@mcp.tool
async def delete_wallet(wid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.wallet_session.delete_wallet(wid)


@mcp.tool
async def deposit(wid: str, amount: float, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.wallet_session.deposit(wid=wid, amount=amount)


@mcp.tool
async def withdraw(wid: str, amount: float, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.wallet_session.withdraw(wid=wid, amount=amount)


@mcp.tool
async def transfer(from_wid: str, to_wid: str, amount: float, session_id: str,
                   memo: str = ""):
    session, err = get_session(session_id)
    if err: return err
    return session.wallet_session.transfer(
        from_wid=from_wid, to_wid=to_wid, amount=amount, memo=memo
    )


@mcp.tool
async def get_balance(wid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.wallet_session.get_balance(wid)


@mcp.tool
async def list_transfers(session_id: str, wid: Optional[str] = None,
                         status: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.wallet_session.list_transfers(wid=wid, status=status)


@mcp.tool
async def get_transfer(trid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.wallet_session.get_transfer(trid)


@mcp.tool
async def cancel_transfer(trid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.wallet_session.cancel_transfer(trid)


@mcp.tool
async def get_total_value_by_currency(currency: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.wallet_session.get_total_value_by_currency(currency=currency)


@mcp.tool
async def list_by_currency(currency: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.wallet_session.list_by_currency(currency=currency)


@mcp.tool
async def search_transfers(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.wallet_session.search_transfers(query)


@mcp.tool
async def get_wallet_history(wid: str, session_id: str, limit: int = 10):
    session, err = get_session(session_id)
    if err: return err
    return session.wallet_session.get_wallet_history(wid=wid, limit=limit)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.wallet_session.get_stats()
