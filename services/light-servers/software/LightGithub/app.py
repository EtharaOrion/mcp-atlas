from typing import Dict, List, Any
from fastmcp import FastMCP
try:
    from session import LightGithubSession
except ImportError:
    from software.LightGithub.session import LightGithubSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


mcp = FastMCP("LightGithub")

session_dict: Dict[str, LightGithubSession] = {}


def get_session(session_id: str):
	session = session_dict.get(session_id)
	if session is None:
		return None, {"status": "failed", "output": "session not found"}
	return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
	session = LightGithubSession(os_cfg=os_cfg, seed=seed)
	session_dict[session.session_id] = session
	logger.info(f"A new user logged in! [{session.session_id}]")
	return {
		"status": "ok",
		"session_id": session.session_id,
		"session_info": {
			"status": "ok",
			"output": session.github_session.get_session_dict()
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
		"output": session.github_session.get_session_dict()
	}


@mcp.tool
async def get_user(session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.github_session.get_user()


@mcp.tool
async def list_user_repos(owner: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.github_session.list_repos(owner)


@mcp.tool
async def list_org_repos(owner: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.github_session.list_repos(owner)


@mcp.tool
async def get_repo(owner: str, repo: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.github_session.get_repo(owner, repo)


@mcp.tool
async def list_issues(owner: str, repo: str, session_id: str, state: str = "open", labels: str | None = None, assignee: str | None = None, per_page: int = 30):
	session, err = get_session(session_id)
	if err:
		return err
	return session.github_session.list_issues(owner, repo, state, labels, assignee, per_page)


@mcp.tool
async def get_issue(owner: str, repo: str, number: int, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.github_session.get_issue(owner, repo, number)


@mcp.tool
async def create_issue(owner: str, repo: str, title: str, session_id: str, body: str = "", assignee: str | None = None, labels: List[str] | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.github_session.create_issue(owner, repo, title, body, assignee, labels)


@mcp.tool
async def update_issue(owner: str, repo: str, number: int, session_id: str, title: str | None = None, body: str | None = None, state: str | None = None, assignee: str | None = None, labels: List[str] | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.github_session.update_issue(owner, repo, number, title, body, state, assignee, labels)


@mcp.tool
async def list_pulls(owner: str, repo: str, session_id: str, state: str = "open"):
	session, err = get_session(session_id)
	if err:
		return err
	return session.github_session.list_pulls(owner, repo, state)


@mcp.tool
async def get_pull(owner: str, repo: str, number: int, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.github_session.get_pull(owner, repo, number)


@mcp.tool
async def merge_pull(owner: str, repo: str, number: int, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.github_session.merge_pull(owner, repo, number)


@mcp.tool
async def list_comments(owner: str, repo: str, number: int, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.github_session.list_comments(owner, repo, number)


@mcp.tool
async def create_comment(owner: str, repo: str, number: int, body: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.github_session.create_comment(owner, repo, number, body)
