from typing import Dict, List, Any
from fastmcp import FastMCP
try:
    from session import LightJiraSession
except ImportError:
    from software.LightJira.session import LightJiraSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


mcp = FastMCP("LightJira")

session_dict: Dict[str, LightJiraSession] = {}


def get_session(session_id: str):
	session = session_dict.get(session_id)
	if session is None:
		return None, {"status": "failed", "output": "session not found"}
	return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
	session = LightJiraSession(os_cfg=os_cfg, seed=seed)
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
		"output": session.jira_session.get_session_dict()
	}


@mcp.tool
async def list_projects(session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.jira_session.list_projects()


@mcp.tool
async def get_issue(issue_key: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.jira_session.get_issue(issue_key)


@mcp.tool
async def create_issue(project_key: str, summary: str, session_id: str, issue_type: str = "Task", description: str = "", priority: str = "Medium", assignee: str | None = None, reporter: str = "user-amelia"):
	session, err = get_session(session_id)
	if err:
		return err
	return session.jira_session.create_issue(project_key, summary, issue_type, description, priority, assignee, reporter)


@mcp.tool
async def update_issue(issue_key: str, session_id: str, summary: str | None = None, description: str | None = None, priority: str | None = None, assignee: str | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.jira_session.update_issue(issue_key, summary, description, priority, assignee)


@mcp.tool
async def get_transitions(issue_key: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.jira_session.get_transitions(issue_key)


@mcp.tool
async def transition_issue(issue_key: str, transition_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.jira_session.transition_issue(issue_key, transition_id)


@mcp.tool
async def search(session_id: str, jql: str | None = None, max_results: int = 50):
	session, err = get_session(session_id)
	if err:
		return err
	return session.jira_session.search(jql, max_results)


@mcp.tool
async def list_boards(session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.jira_session.list_boards()


@mcp.tool
async def list_sprints(board_id: int, session_id: str, state: str | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.jira_session.list_sprints(board_id, state)
