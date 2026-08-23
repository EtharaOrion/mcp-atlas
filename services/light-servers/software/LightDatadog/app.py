from typing import Dict, List, Any
from fastmcp import FastMCP
try:
    from session import LightDatadogSession
except ImportError:
    from software.LightDatadog.session import LightDatadogSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


mcp = FastMCP("LightDatadog")

session_dict: Dict[str, LightDatadogSession] = {}


def get_session(session_id: str):
	session = session_dict.get(session_id)
	if session is None:
		return None, {"status": "failed", "output": "session not found"}
	return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
	session = LightDatadogSession(os_cfg=os_cfg, seed=seed)
	session_dict[session.session_id] = session
	logger.info(f"A new user logged in! [{session.session_id}]")
	return {
		"status": "ok",
		"session_id": session.session_id,
		"session_info": {
			"status": "ok",
			"output": session.datadog_session.get_session_dict()
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
		"output": session.datadog_session.get_session_dict()
	}


@mcp.tool
async def query_metrics(query: str, from_: int, to: int, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.datadog_session.query_metrics(query, from_, to)


@mcp.tool
async def list_monitors(session_id: str, overall_state: str | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.datadog_session.list_monitors(overall_state)


@mcp.tool
async def get_monitor(monitor_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.datadog_session.get_monitor(monitor_id)


@mcp.tool
async def create_monitor(name: str, type: str, query: str, session_id: str, message: str = "", priority: int = 3, tags: List[str] | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.datadog_session.create_monitor(name, type, query, message, priority, tags)


@mcp.tool
async def update_monitor(monitor_id: str, session_id: str, name: str | None = None, query: str | None = None, message: str | None = None, overall_state: str | None = None, priority: int | None = None, tags: List[str] | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.datadog_session.update_monitor(monitor_id, name, query, message, overall_state, priority, tags)


@mcp.tool
async def list_dashboards(session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.datadog_session.list_dashboards()


@mcp.tool
async def get_dashboard(dashboard_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.datadog_session.get_dashboard(dashboard_id)


@mcp.tool
async def list_events(session_id: str, start: int | None = None, end: int | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.datadog_session.list_events(start, end)


@mcp.tool
async def create_event(title: str, text: str, session_id: str, alert_type: str = "info", priority: str = "normal", host: str | None = None, tags: List[str] | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.datadog_session.create_event(title, text, alert_type, priority, host, tags)


@mcp.tool
async def list_hosts(session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.datadog_session.list_hosts()
