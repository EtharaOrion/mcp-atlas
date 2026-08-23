from typing import Dict, List, Any
from fastmcp import FastMCP
try:
    from session import LightPagerDutySession
except ImportError:
    from software.LightPagerDuty.session import LightPagerDutySession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


mcp = FastMCP("LightPagerDuty")

session_dict: Dict[str, LightPagerDutySession] = {}


def get_session(session_id: str):
	session = session_dict.get(session_id)
	if session is None:
		return None, {"status": "failed", "output": "session not found"}
	return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
	session = LightPagerDutySession(os_cfg=os_cfg, seed=seed)
	session_dict[session.session_id] = session
	logger.info(f"A new user logged in! [{session.session_id}]")
	return {
		"status": "ok",
		"session_id": session.session_id,
		"session_info": {
			"status": "ok",
			"output": session.pagerduty_session.get_session_dict()
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
		"output": session.pagerduty_session.get_session_dict()
	}


@mcp.tool
async def list_users(session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.pagerduty_session.list_users()


@mcp.tool
async def list_services(session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.pagerduty_session.list_services()


@mcp.tool
async def get_service(service_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.pagerduty_session.get_service(service_id)


@mcp.tool
async def list_incidents(session_id: str, statuses: List[str] | None = None, service_id: str | None = None, urgency: str | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.pagerduty_session.list_incidents(statuses, service_id, urgency)


@mcp.tool
async def get_incident(incident_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.pagerduty_session.get_incident(incident_id)


@mcp.tool
async def create_incident(title: str, service_id: str, session_id: str, urgency: str = "high", assigned_to: str | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.pagerduty_session.create_incident(title, service_id, urgency, assigned_to)


@mcp.tool
async def update_incident(incident_id: str, session_id: str, status: str | None = None, assigned_to: str | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.pagerduty_session.update_incident(incident_id, status, assigned_to)


@mcp.tool
async def list_notes(incident_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.pagerduty_session.list_notes(incident_id)


@mcp.tool
async def create_note(incident_id: str, content: str, session_id: str, user_id: str | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.pagerduty_session.create_note(incident_id, content, user_id)


@mcp.tool
async def list_oncalls(session_id: str, escalation_policy_id: str | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.pagerduty_session.list_oncalls(escalation_policy_id)


@mcp.tool
async def list_schedules(session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.pagerduty_session.list_schedules()


@mcp.tool
async def list_escalation_policies(session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.pagerduty_session.list_escalation_policies()
