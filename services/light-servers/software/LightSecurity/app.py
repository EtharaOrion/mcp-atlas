from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightSecuritySession
except ImportError:
    from software.LightSecurity.session import LightSecuritySession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightSecurity")

session_dict: Dict[str, LightSecuritySession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightSecuritySession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.security_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.security_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_cameras(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.list_cameras()


@mcp.tool
async def get_camera(caid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.get_camera(caid)


@mcp.tool
async def add_camera(name: str, room: str, session_id: str,
                     resolution: str = "1080p", night_vision: bool = True):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.add_camera(
        name=name, room=room, resolution=resolution, night_vision=night_vision,
    )


@mcp.tool
async def start_recording(caid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.start_recording(caid)


@mcp.tool
async def stop_recording(caid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.stop_recording(caid)


@mcp.tool
async def list_sensors(session_id: str, kind: Optional[str] = None, room: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.list_sensors(kind=kind, room=room)


@mcp.tool
async def get_sensor(seid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.get_sensor(seid)


@mcp.tool
async def arm_sensor(seid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.arm_sensor(seid)


@mcp.tool
async def disarm_sensor(seid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.disarm_sensor(seid)


@mcp.tool
async def trigger_sensor(seid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.trigger_sensor(seid)


@mcp.tool
async def list_alarms(session_id: str, resolved: Optional[bool] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.list_alarms(resolved=resolved)


@mcp.tool
async def resolve_alarm(alid: str, session_id: str, notes: str = ""):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.resolve_alarm(alid, notes=notes)


@mcp.tool
async def list_events(session_id: str, kind: Optional[str] = None, source_kind: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.list_events(kind=kind, source_kind=source_kind)


@mcp.tool
async def record_event(source_kind: str, source_id: str, kind: str, session_id: str,
                       description: str = ""):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.record_event(
        source_kind=source_kind, source_id=source_id, kind=kind, description=description,
    )


@mcp.tool
async def list_access_logs(session_id: str, user: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.list_access_logs(user=user)


@mcp.tool
async def record_access(user: str, action: str, method: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.record_access(user=user, action=action, method=method)


@mcp.tool
async def arm_all_sensors(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.arm_all_sensors()


@mcp.tool
async def disarm_all_sensors(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.disarm_all_sensors()


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.security_session.get_stats()


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=9035)
