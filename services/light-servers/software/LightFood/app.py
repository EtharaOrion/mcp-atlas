from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightFoodSession
except ImportError:
    from software.LightFood.session import LightFoodSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightFood")

session_dict: Dict[str, LightFoodSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightFoodSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.food_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.food_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_restaurants(session_id: str, cuisine: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.food_session.list_restaurants(cuisine=cuisine)


@mcp.tool
async def get_restaurant(restid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.food_session.get_restaurant(restid)


@mcp.tool
async def list_menu(restaurant_id: str, session_id: str, category: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.food_session.list_menu(restaurant_id=restaurant_id, category=category)


@mcp.tool
async def get_menu_item(miid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.food_session.get_menu_item(miid)


@mcp.tool
async def add_menu_item(restaurant_id: str, name: str, description: str,
                        price: float, category: str, session_id: str,
                        available: bool = True, currency: str = "USD"):
    session, err = get_session(session_id)
    if err: return err
    return session.food_session.add_menu_item(
        restaurant_id=restaurant_id, name=name, description=description,
        price=price, category=category, available=available, currency=currency,
    )


@mcp.tool
async def update_menu_item(miid: str, session_id: str,
                           name: Optional[str] = None,
                           description: Optional[str] = None,
                           price: Optional[float] = None,
                           category: Optional[str] = None,
                           available: Optional[bool] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.food_session.update_menu_item(
        miid=miid, name=name, description=description,
        price=price, category=category, available=available,
    )


@mcp.tool
async def list_orders(session_id: str, status: Optional[str] = None, customer: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.food_session.list_orders(status=status, customer=customer)


@mcp.tool
async def get_order(oid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.food_session.get_order(oid)


@mcp.tool
async def place_order(restaurant_id: str, customer: str, items: List[Dict],
                      address: str, session_id: str, tip: float = 0.0):
    session, err = get_session(session_id)
    if err: return err
    return session.food_session.place_order(
        restaurant_id=restaurant_id, customer=customer,
        items=items, address=address, tip=tip,
    )


@mcp.tool
async def cancel_order(oid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.food_session.cancel_order(oid)


@mcp.tool
async def confirm_order(oid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.food_session.confirm_order(oid)


@mcp.tool
async def start_preparation(oid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.food_session.start_preparation(oid)


@mcp.tool
async def mark_out_for_delivery(oid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.food_session.mark_out_for_delivery(oid)


@mcp.tool
async def mark_delivered(oid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.food_session.mark_delivered(oid)


@mcp.tool
async def search_restaurants(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.food_session.search_restaurants(query)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.food_session.get_stats()
