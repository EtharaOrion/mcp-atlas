from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightCalendarSession
except ImportError:
    from software.LightCalendar.session import LightCalendarSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightCalendar")

session_dict: Dict[str, LightCalendarSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightCalendarSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.calendar_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.calendar_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_calendars(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.calendar_session.list_calendars()


@mcp.tool
async def create_calendar(name: str, session_id: str, color: str = "#888888"):
    session, err = get_session(session_id)
    if err: return err
    return session.calendar_session.create_calendar(name=name, color=color)


@mcp.tool
async def delete_calendar(cid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.calendar_session.delete_calendar(cid)


@mcp.tool
async def list_events(session_id: str, calendar_id: Optional[str] = None,
                      start_date: Optional[str] = None, end_date: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.calendar_session.list_events(
        calendar_id=calendar_id, start_date=start_date, end_date=end_date
    )


@mcp.tool
async def get_event(eid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.calendar_session.get_event(eid)


@mcp.tool
async def create_event(title: str, start: str, end: str, session_id: str,
                       calendar_id: str = "cal_personal",
                       location: str = "", description: str = "",
                       attendees: Optional[List[str]] = None,
                       all_day: bool = False):
    session, err = get_session(session_id)
    if err: return err
    return session.calendar_session.create_event(
        title=title, start=start, end=end, calendar_id=calendar_id,
        location=location, description=description,
        attendees=attendees, all_day=all_day,
    )


@mcp.tool
async def update_event(eid: str, session_id: str,
                       title: Optional[str] = None,
                       start: Optional[str] = None,
                       end: Optional[str] = None,
                       location: Optional[str] = None,
                       description: Optional[str] = None,
                       calendar_id: Optional[str] = None,
                       attendees: Optional[List[str]] = None,
                       all_day: Optional[bool] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.calendar_session.update_event(
        eid=eid, title=title, start=start, end=end, location=location,
        description=description, calendar_id=calendar_id,
        attendees=attendees, all_day=all_day,
    )


@mcp.tool
async def delete_event(eid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.calendar_session.delete_event(eid)


@mcp.tool
async def move_event(eid: str, new_start: str, new_end: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.calendar_session.move_event(eid, new_start, new_end)


@mcp.tool
async def search_events(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.calendar_session.search_events(query)


@mcp.tool
async def list_upcoming(session_id: str, limit: int = 5, from_date: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.calendar_session.list_upcoming(limit=limit, from_date=from_date)


@mcp.tool
async def list_today(session_id: str, today: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.calendar_session.list_today(today=today)


@mcp.tool
async def check_availability(start: str, end: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.calendar_session.check_availability(start, end)


@mcp.tool
async def find_free_slot(duration_min: int, start_date: str, end_date: str, session_id: str,
                         working_hours_start: int = 9, working_hours_end: int = 18):
    session, err = get_session(session_id)
    if err: return err
    return session.calendar_session.find_free_slot(
        duration_min=duration_min, start_date=start_date, end_date=end_date,
        working_hours_start=working_hours_start, working_hours_end=working_hours_end,
    )
