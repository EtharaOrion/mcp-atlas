from typing import Dict, List, Any
from fastmcp import FastMCP
try:
    from session import LightConfluenceSession
except ImportError:
    from software.LightConfluence.session import LightConfluenceSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


mcp = FastMCP("LightConfluence")

session_dict: Dict[str, LightConfluenceSession] = {}


def get_session(session_id: str):
	session = session_dict.get(session_id)
	if session is None:
		return None, {"status": "failed", "output": "session not found"}
	return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
	session = LightConfluenceSession(os_cfg=os_cfg, seed=seed)
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
		"output": session.confluence_session.get_session_dict()
	}


@mcp.tool
async def list_spaces(session_id: str, limit: int = 25):
	session, err = get_session(session_id)
	if err:
		return err
	return session.confluence_session.list_spaces(limit)


@mcp.tool
async def get_space(space_key: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.confluence_session.get_space(space_key)


@mcp.tool
async def list_content(session_id: str, type: str = "page", space_key: str | None = None, limit: int = 25):
	session, err = get_session(session_id)
	if err:
		return err
	return session.confluence_session.list_content(type, space_key, limit)


@mcp.tool
async def get_content(content_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.confluence_session.get_content(content_id)


@mcp.tool
async def create_content(title: str, space_key: str, session_id: str, body: str = "", parent_id: str | None = None, created_by: str = "apiuser"):
	session, err = get_session(session_id)
	if err:
		return err
	return session.confluence_session.create_content(title, space_key, body, parent_id, created_by)


@mcp.tool
async def update_content(content_id: str, session_id: str, title: str | None = None, body: str | None = None, version_number: int | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.confluence_session.update_content(content_id, title, body, version_number)


@mcp.tool
async def list_child_pages(content_id: str, session_id: str, limit: int = 25):
	session, err = get_session(session_id)
	if err:
		return err
	return session.confluence_session.list_child_pages(content_id, limit)


@mcp.tool
async def list_labels(content_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.confluence_session.list_labels(content_id)


@mcp.tool
async def list_comments(content_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.confluence_session.list_comments(content_id)


@mcp.tool
async def search_content(cql: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.confluence_session.search_content(cql)
