from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightHomeSession
except ImportError:
    from software.LightHome.session import LightHomeSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightHome")

session_dict: Dict[str, LightHomeSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightHomeSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.home_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.home_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_rooms(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.home_session.list_rooms()


@mcp.tool
async def add_room(name: str, floor: int, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.home_session.add_room(name=name, floor=floor)


@mcp.tool
async def list_devices(session_id: str, room_id: Optional[str] = None, kind: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.home_session.list_devices(room_id=room_id, kind=kind)


@mcp.tool
async def get_device(dvid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.home_session.get_device(dvid)


@mcp.tool
async def add_device(name: str, room_id: str, kind: str, session_id: str,
                     brightness: Optional[int] = None,
                     temperature: Optional[float] = None,
                     color: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.home_session.add_device(
        name=name, room_id=room_id, kind=kind,
        brightness=brightness, temperature=temperature, color=color,
    )


@mcp.tool
async def remove_device(dvid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.home_session.remove_device(dvid)


@mcp.tool
async def turn_on(dvid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.home_session.turn_on(dvid)


@mcp.tool
async def turn_off(dvid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.home_session.turn_off(dvid)


@mcp.tool
async def set_brightness(dvid: str, brightness: int, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.home_session.set_brightness(dvid, brightness)


@mcp.tool
async def set_temperature(dvid: str, temperature: float, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.home_session.set_temperature(dvid, temperature)


@mcp.tool
async def set_color(dvid: str, color: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.home_session.set_color(dvid, color)


@mcp.tool
async def list_scenes(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.home_session.list_scenes()


@mcp.tool
async def get_scene(scid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.home_session.get_scene(scid)


@mcp.tool
async def create_scene(name: str, actions: List[Dict], session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.home_session.create_scene(name=name, actions=actions)


@mcp.tool
async def activate_scene(scid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.home_session.activate_scene(scid)


@mcp.tool
async def list_automations(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.home_session.list_automations()


@mcp.tool
async def toggle_automation(auid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.home_session.toggle_automation(auid)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.home_session.get_stats()


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=9034)
