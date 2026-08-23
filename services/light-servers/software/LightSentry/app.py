from typing import Dict, List, Any
from fastmcp import FastMCP
try:
    from session import LightSentrySession
except ImportError:
    from software.LightSentry.session import LightSentrySession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


mcp = FastMCP("LightSentry")

session_dict: Dict[str, LightSentrySession] = {}


def get_session(session_id: str):
	session = session_dict.get(session_id)
	if session is None:
		return None, {"status": "failed", "output": "session not found"}
	return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
	session = LightSentrySession(os_cfg=os_cfg, seed=seed)
	session_dict[session.session_id] = session
	logger.info(f"A new user logged in! [{session.session_id}]")
	return {
		"status": "ok",
		"session_id": session.session_id,
		"session_info": {
			"status": "ok",
			"output": session.sentry_session.get_session_dict()
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
		"output": session.sentry_session.get_session_dict()
	}


@mcp.tool
async def list_org_projects(org_slug: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.sentry_session.list_org_projects(org_slug)


@mcp.tool
async def list_project_issues(org_slug: str, project_slug: str, session_id: str, status: str | None = None, level: str | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.sentry_session.list_project_issues(org_slug, project_slug, status, level)


@mcp.tool
async def get_issue(org_slug: str, issue_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.sentry_session.get_issue(org_slug, issue_id)


@mcp.tool
async def update_issue(org_slug: str, issue_id: str, status: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.sentry_session.update_issue(org_slug, issue_id, status)


@mcp.tool
async def list_issue_events(org_slug: str, issue_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.sentry_session.list_issue_events(org_slug, issue_id)


@mcp.tool
async def list_releases(org_slug: str, session_id: str, project: str | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.sentry_session.list_releases(org_slug, project)
