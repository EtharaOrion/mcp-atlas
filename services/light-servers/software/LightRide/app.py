from typing import Dict, Optional
from fastmcp import FastMCP
try:
    from session import LightRideSession
except ImportError:
    from software.LightRide.session import LightRideSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightRide")

session_dict: Dict[str, LightRideSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightRideSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.ride_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.ride_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_rides(session_id: str, status: Optional[str] = None, rider: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.ride_session.list_rides(status=status, rider=rider)


@mcp.tool
async def get_ride(rid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.ride_session.get_ride(rid)


@mcp.tool
async def request_ride(rider: str, pickup: str, dropoff: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.ride_session.request_ride(rider=rider, pickup=pickup, dropoff=dropoff)


@mcp.tool
async def accept_ride(rid: str, did: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.ride_session.accept_ride(rid=rid, did=did)


@mcp.tool
async def start_ride(rid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.ride_session.start_ride(rid=rid)


@mcp.tool
async def complete_ride(rid: str, fare: float, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.ride_session.complete_ride(rid=rid, fare=fare)


@mcp.tool
async def cancel_ride(rid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.ride_session.cancel_ride(rid=rid)


@mcp.tool
async def rate_ride(rid: str, rating: int, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.ride_session.rate_ride(rid=rid, rating=rating)


@mcp.tool
async def list_drivers(session_id: str, is_available: Optional[bool] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.ride_session.list_drivers(is_available=is_available)


@mcp.tool
async def get_driver(did: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.ride_session.get_driver(did)


@mcp.tool
async def add_driver(name: str, car_model: str, license_plate: str, session_id: str,
                     rating: float = 5.0, is_available: bool = True):
    session, err = get_session(session_id)
    if err: return err
    return session.ride_session.add_driver(
        name=name, car_model=car_model, license_plate=license_plate,
        rating=rating, is_available=is_available,
    )


@mcp.tool
async def list_riders(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.ride_session.list_riders()


@mcp.tool
async def add_rider(name: str, session_id: str, home_address: str = "", work_address: str = ""):
    session, err = get_session(session_id)
    if err: return err
    return session.ride_session.add_rider(name=name, home_address=home_address, work_address=work_address)


@mcp.tool
async def add_saved_place(ruid: str, place: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.ride_session.add_saved_place(ruid=ruid, place=place)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.ride_session.get_stats()
