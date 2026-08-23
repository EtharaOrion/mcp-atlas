from typing import Dict, Optional
from fastmcp import FastMCP
try:
    from session import LightRentalSession
except ImportError:
    from software.LightRental.session import LightRentalSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightRental")

session_dict: Dict[str, LightRentalSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightRentalSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.rental_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.rental_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_assets(session_id: str, category: Optional[str] = None, is_available: Optional[bool] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.rental_session.list_assets(category=category, is_available=is_available)


@mcp.tool
async def get_asset(aid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.rental_session.get_asset(aid)


@mcp.tool
async def add_asset(name: str, category: str, daily_rate: float, location: str, session_id: str,
                    condition: str = "good", is_available: bool = True, currency: str = "USD"):
    session, err = get_session(session_id)
    if err: return err
    return session.rental_session.add_asset(
        name=name, category=category, daily_rate=daily_rate, location=location,
        condition=condition, is_available=is_available, currency=currency,
    )


@mcp.tool
async def list_bookings(session_id: str, status: Optional[str] = None, renter: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.rental_session.list_bookings(status=status, renter=renter)


@mcp.tool
async def get_booking(bid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.rental_session.get_booking(bid)


@mcp.tool
async def book_asset(aid: str, renter: str, start_date: str, end_date: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.rental_session.book_asset(aid=aid, renter=renter, start_date=start_date, end_date=end_date)


@mcp.tool
async def cancel_booking(bid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.rental_session.cancel_booking(bid)


@mcp.tool
async def return_asset(bid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.rental_session.return_asset(bid)


@mcp.tool
async def report_damage(aid: str, bid: str, description: str, cost: float, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.rental_session.report_damage(aid=aid, bid=bid, description=description, cost=cost)


@mcp.tool
async def list_damages(session_id: str, asset_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.rental_session.list_damages(asset_id=asset_id)


@mcp.tool
async def get_asset_availability(aid: str, start_date: str, end_date: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.rental_session.get_asset_availability(aid=aid, start_date=start_date, end_date=end_date)


@mcp.tool
async def get_asset_revenue(aid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.rental_session.get_asset_revenue(aid)


@mcp.tool
async def search_assets(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.rental_session.search_assets(query)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.rental_session.get_stats()
