from typing import Dict, List, Any
from fastmcp import FastMCP
try:
    from session import LightSegmentSession
except ImportError:
    from software.LightSegment.session import LightSegmentSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


mcp = FastMCP("LightSegment")

session_dict: Dict[str, LightSegmentSession] = {}


def get_session(session_id: str):
	session = session_dict.get(session_id)
	if session is None:
		return None, {"status": "failed", "output": "session not found"}
	return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
	session = LightSegmentSession(os_cfg=os_cfg, seed=seed)
	session_dict[session.session_id] = session
	logger.info(f"A new user logged in! [{session.session_id}]")
	return {
		"status": "ok",
		"session_id": session.session_id,
		"session_info": {
			"status": "ok",
			"output": {}
        }
    }


@mcp.tool
async def logout(session_id: str | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	del session_dict[session_id]
	logger.info(f"A user logged out! [{session_id}]")
	return {
        "status": "ok",
        "output": session.segment_session.get_session_dict(),
    }


@mcp.tool
async def track(body: Dict[str, Any], session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.segment_session.track(body)


@mcp.tool
async def identify(body: Dict[str, Any], session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.segment_session.identify(body)


@mcp.tool
async def page(body: Dict[str, Any], session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.segment_session.page(body)


@mcp.tool
async def batch(body: Dict[str, Any], session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.segment_session.batch(body)


@mcp.tool
async def list_events(session_id: str, event_type: str | None = None, user_id: str | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.segment_session.list_events(event_type, user_id)


@mcp.tool
async def list_sources(session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.segment_session.list_sources()


@mcp.tool
async def list_destinations(session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.segment_session.list_destinations()


@mcp.tool
async def delete_event(message_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.segment_session.delete_event(message_id)

@mcp.tool
async def update_destination(destination_id: str, session_id: str, enabled: bool | None = None, settings: Dict[str, Any] | None = None):
    s = get_session(session_id)
    return s.segment_session.update_destination(destination_id, enabled=enabled, settings=settings)

