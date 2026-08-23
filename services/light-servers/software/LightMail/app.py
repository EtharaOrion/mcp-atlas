from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightMailSession
except ImportError:
    from software.LightMail.session import LightMailSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightMail")

session_dict: Dict[str, LightMailSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightMailSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.mail_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.mail_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_folders(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.mail_session.list_folders()


@mcp.tool
async def list_messages(folder: str, session_id: str, limit: int = 20, offset: int = 0):
    session, err = get_session(session_id)
    if err: return err
    return session.mail_session.list_messages(folder=folder, limit=limit, offset=offset)


@mcp.tool
async def get_message(mid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.mail_session.get_message(mid)


@mcp.tool
async def mark_as_read(mid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.mail_session.mark_as_read(mid)


@mcp.tool
async def mark_as_unread(mid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.mail_session.mark_as_unread(mid)


@mcp.tool
async def star(mid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.mail_session.star(mid)


@mcp.tool
async def unstar(mid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.mail_session.unstar(mid)


@mcp.tool
async def move_to_folder(mid: str, folder: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.mail_session.move_to_folder(mid, folder)


@mcp.tool
async def delete_message(mid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.mail_session.delete_message(mid)


@mcp.tool
async def compose_email(to: List[str], subject: str, body: str, session_id: str, cc: Optional[List[str]] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.mail_session.compose_email(to=to, subject=subject, body=body, cc=cc)


@mcp.tool
async def send_email(mid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.mail_session.send_email(mid)


@mcp.tool
async def reply(mid: str, body: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.mail_session.reply(mid, body)


@mcp.tool
async def search_messages(query: str, session_id: str, folder: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.mail_session.search_messages(query=query, folder=folder)
