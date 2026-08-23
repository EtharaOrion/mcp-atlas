from typing import Dict, List, Any
from fastmcp import FastMCP
try:
    from session import LightNotionSession
except ImportError:
    from software.LightNotion.session import LightNotionSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


mcp = FastMCP("LightNotion")

session_dict: Dict[str, LightNotionSession] = {}


def get_session(session_id: str):
	session = session_dict.get(session_id)
	if session is None:
		return None, {"status": "failed", "output": "session not found"}
	return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
	session = LightNotionSession(os_cfg=os_cfg, seed=seed)
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
		"output": session.notion_session.get_session_dict()
	}


@mcp.tool
async def list_users(session_id: str, start_cursor: str | None = None, page_size: int = 50):
	session, err = get_session(session_id)
	if err:
		return err
	return session.notion_session.list_users(start_cursor, page_size)


@mcp.tool
async def get_user(user_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.notion_session.get_user(user_id)


@mcp.tool
async def get_me(session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.notion_session.get_me()


@mcp.tool
async def get_workspace(session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.notion_session.get_workspace()


@mcp.tool
async def search(session_id: str, query: str | None = None, filter_value: str | None = None, start_cursor: str | None = None, page_size: int = 50):
	session, err = get_session(session_id)
	if err:
		return err
	return session.notion_session.search(query, filter_value, start_cursor, page_size)


@mcp.tool
async def get_database(database_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.notion_session.get_database(database_id)


@mcp.tool
async def query_database(database_id: str, session_id: str, filter_status: str | None = None, filter_assignee: str | None = None, sort_by: str | None = None, start_cursor: str | None = None, page_size: int = 50):
	session, err = get_session(session_id)
	if err:
		return err
	return session.notion_session.query_database(database_id, filter_status, filter_assignee, sort_by, start_cursor, page_size)


@mcp.tool
async def get_page(page_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.notion_session.get_page(page_id)


@mcp.tool
async def create_page(parent_type: str, parent_id: str, title: str, session_id: str, properties: Dict[str, Any] | None = None, created_by: str = "user-amelia"):
	session, err = get_session(session_id)
	if err:
		return err
	return session.notion_session.create_page(parent_type, parent_id, title, properties, created_by)


@mcp.tool
async def update_page(page_id: str, session_id: str, title: str | None = None, archived: bool | None = None, properties: Dict[str, Any] | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.notion_session.update_page(page_id, title, archived, properties)


@mcp.tool
async def delete_page(page_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.notion_session.delete_page(page_id)


@mcp.tool
async def list_block_children(block_id: str, session_id: str, start_cursor: str | None = None, page_size: int = 50):
	session, err = get_session(session_id)
	if err:
		return err
	return session.notion_session.list_block_children(block_id, start_cursor, page_size)


@mcp.tool
async def append_block_children(block_id: str, children: List[Dict[str, Any]], session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.notion_session.append_block_children(block_id, children)


@mcp.tool
async def update_block(block_id: str, session_id: str, text: str | None = None, checked: bool | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.notion_session.update_block(block_id, text, checked)


@mcp.tool
async def delete_block(block_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.notion_session.delete_block(block_id)


@mcp.tool
async def list_comments(session_id: str, block_id: str | None = None, page_id: str | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.notion_session.list_comments(block_id, page_id)


@mcp.tool
async def create_comment(parent_page_id: str, author_id: str, text: str, session_id: str, parent_block_id: str | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.notion_session.create_comment(parent_page_id, author_id, text, parent_block_id)
