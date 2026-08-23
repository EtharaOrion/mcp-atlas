from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightMeetSession
except ImportError:
    from software.LightMeet.session import LightMeetSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightMeet")

session_dict: Dict[str, LightMeetSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightMeetSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.meet_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.meet_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_meetings(session_id: str, status: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.meet_session.list_meetings(status=status)


@mcp.tool
async def get_meeting(mid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.meet_session.get_meeting(mid)


@mcp.tool
async def create_meeting(title: str, start: str, end: str, session_id: str,
                         description: str = "",
                         host: str = "self",
                         participants: Optional[List[str]] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.meet_session.create_meeting(
        title=title, start=start, end=end,
        description=description, host=host, participants=participants,
    )


@mcp.tool
async def update_meeting(mid: str, session_id: str,
                         title: Optional[str] = None,
                         description: Optional[str] = None,
                         start: Optional[str] = None,
                         end: Optional[str] = None,
                         host: Optional[str] = None,
                         notes: Optional[str] = None,
                         participants: Optional[List[str]] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.meet_session.update_meeting(
        mid=mid, title=title, description=description,
        start=start, end=end, host=host, notes=notes,
        participants=participants,
    )


@mcp.tool
async def cancel_meeting(mid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.meet_session.cancel_meeting(mid)


@mcp.tool
async def list_upcoming(session_id: str, days: int = 7, today: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.meet_session.list_upcoming(days=days, today=today)


@mcp.tool
async def list_today(session_id: str, today: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.meet_session.list_today(today=today)


@mcp.tool
async def list_past(session_id: str, today: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.meet_session.list_past(today=today)


@mcp.tool
async def add_participant(mid: str, email: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.meet_session.add_participant(mid, email)


@mcp.tool
async def remove_participant(mid: str, email: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.meet_session.remove_participant(mid, email)


@mcp.tool
async def generate_recording_link(mid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.meet_session.generate_recording_link(mid)


@mcp.tool
async def set_transcript(mid: str, text: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.meet_session.set_transcript(mid, text)


@mcp.tool
async def get_transcript(mid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.meet_session.get_transcript(mid)


@mcp.tool
async def search_meetings(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.meet_session.search_meetings(query)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.meet_session.get_stats()
