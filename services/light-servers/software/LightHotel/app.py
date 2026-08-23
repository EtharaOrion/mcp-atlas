from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightHotelSession
except ImportError:
    from software.LightHotel.session import LightHotelSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightHotel")

session_dict: Dict[str, LightHotelSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightHotelSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.hotel_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.hotel_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_hotels(session_id: str, city: Optional[str] = None, star_rating: Optional[int] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.hotel_session.list_hotels(city=city, star_rating=star_rating)


@mcp.tool
async def get_hotel(hid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.hotel_session.get_hotel(hid)


@mcp.tool
async def add_hotel(name: str, city: str, star_rating: int, price_per_night: float, session_id: str,
                    amenities: Optional[List[str]] = None, currency: str = "USD"):
    session, err = get_session(session_id)
    if err: return err
    return session.hotel_session.add_hotel(
        name=name, city=city, star_rating=star_rating,
        price_per_night=price_per_night, amenities=amenities, currency=currency,
    )


@mcp.tool
async def list_reservations(session_id: str, status: Optional[str] = None, hotel_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.hotel_session.list_reservations(status=status, hotel_id=hotel_id)


@mcp.tool
async def get_reservation(resid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.hotel_session.get_reservation(resid)


@mcp.tool
async def create_reservation(hotel_id: str, guest: str, check_in: str, check_out: str,
                             room_type: str, session_id: str, guests_count: int = 1):
    session, err = get_session(session_id)
    if err: return err
    return session.hotel_session.create_reservation(
        hotel_id=hotel_id, guest=guest, check_in=check_in, check_out=check_out,
        room_type=room_type, guests_count=guests_count,
    )


@mcp.tool
async def cancel_reservation(resid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.hotel_session.cancel_reservation(resid)


@mcp.tool
async def check_in(resid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.hotel_session.check_in(resid)


@mcp.tool
async def check_out(resid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.hotel_session.check_out(resid)


@mcp.tool
async def list_reviews(session_id: str, hotel_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.hotel_session.list_reviews(hotel_id=hotel_id)


@mcp.tool
async def add_review(hotel_id: str, guest: str, rating: int, comment: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.hotel_session.add_review(hotel_id=hotel_id, guest=guest, rating=rating, comment=comment)


@mcp.tool
async def get_average_rating(hid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.hotel_session.get_average_rating(hid)


@mcp.tool
async def search_hotels(city: str, check_in: str, check_out: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.hotel_session.search_hotels(city=city, check_in=check_in, check_out=check_out)


@mcp.tool
async def list_upcoming_stays(guest: str, session_id: str, today: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.hotel_session.list_upcoming_stays(guest=guest, today=today)


@mcp.tool
async def get_amenities(hid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.hotel_session.get_amenities(hid)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.hotel_session.get_stats()
