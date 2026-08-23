from typing import Dict, List, Any
from fastmcp import FastMCP
try:
    from session import LightSlackSession
except ImportError:
    from software.LightSlack.session import LightSlackSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


mcp = FastMCP("LightSlack")

session_dict: Dict[str, LightSlackSession] = {}


def get_session(session_id: str):
	session = session_dict.get(session_id)
	if session is None:
		return None, {"status": "failed", "output": "session not found"}
	return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
	session = LightSlackSession(os_cfg=os_cfg, seed=seed)
	session_dict[session.session_id] = session
	logger.info(f"A new user logged in! [{session.session_id}]")
	return {
		"status": "ok",
		"session_id": session.session_id,
		"session_info": {
			"status": "ok",
			"output": session.slack_session.get_session_dict()
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
		"output": session.slack_session.get_session_dict()
	}


@mcp.tool
async def auth_test(session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.slack_session.auth_test()


@mcp.tool
async def team_info(session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.slack_session.team_info()


@mcp.tool
async def users_list(session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.slack_session.users_list()


@mcp.tool
async def users_info(user: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.slack_session.users_info(user)


@mcp.tool
async def users_set_presence(user: str, presence: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.slack_session.users_set_presence(user, presence)


@mcp.tool
async def conversations_list(session_id: str, types: str = "public_channel,private_channel", exclude_archived: bool = True):
	session, err = get_session(session_id)
	if err:
		return err
	return session.slack_session.conversations_list(types, exclude_archived)


@mcp.tool
async def conversations_info(channel: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.slack_session.conversations_info(channel)


@mcp.tool
async def conversations_create(name: str, session_id: str, is_private: bool = False, user_id: str = "U01AMELIA"):
	session, err = get_session(session_id)
	if err:
		return err
	return session.slack_session.conversations_create(name, is_private, user_id)


@mcp.tool
async def conversations_archive(channel: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.slack_session.conversations_archive(channel)


@mcp.tool
async def conversations_members(channel: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.slack_session.conversations_members(channel)


@mcp.tool
async def conversations_invite(channel: str, users: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.slack_session.conversations_invite(channel, users)


@mcp.tool
async def conversations_history(channel: str, session_id: str, limit: int = 20, oldest: str | None = None, latest: str | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.slack_session.conversations_history(channel, limit, oldest, latest)


@mcp.tool
async def conversations_replies(channel: str, ts: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.slack_session.conversations_replies(channel, ts)


@mcp.tool
async def chat_post_message(channel: str, text: str, session_id: str, user: str = "U01AMELIA", thread_ts: str | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.slack_session.chat_post_message(channel, text, user, thread_ts)


@mcp.tool
async def chat_update(channel: str, ts: str, text: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.slack_session.chat_update(channel, ts, text)


@mcp.tool
async def chat_delete(channel: str, ts: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.slack_session.chat_delete(channel, ts)


@mcp.tool
async def reactions_add(channel: str, timestamp: str, name: str, session_id: str, user: str = "U01AMELIA"):
	session, err = get_session(session_id)
	if err:
		return err
	return session.slack_session.reactions_add(channel, timestamp, name, user)


@mcp.tool
async def search_messages(query: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.slack_session.search_messages(query)
