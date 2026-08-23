from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightNotesSession
except ImportError:
    from software.LightNotes.session import LightNotesSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightNotes")

session_dict: Dict[str, LightNotesSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightNotesSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.notes_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.notes_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_notebooks(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.notes_session.list_notebooks()


@mcp.tool
async def create_notebook(name: str, session_id: str, color: str = "#888888", description: str = ""):
    session, err = get_session(session_id)
    if err: return err
    return session.notes_session.create_notebook(name=name, color=color, description=description)


@mcp.tool
async def delete_notebook(nbid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.notes_session.delete_notebook(nbid)


@mcp.tool
async def list_notes(session_id: str,
                     notebook_id: Optional[str] = None,
                     tag: Optional[str] = None,
                     archived: Optional[bool] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.notes_session.list_notes(
        notebook_id=notebook_id, tag=tag, archived=archived,
    )


@mcp.tool
async def get_note(nid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.notes_session.get_note(nid)


@mcp.tool
async def create_note(title: str, session_id: str,
                      content: str = "",
                      notebook_id: str = "nb_personal",
                      tags: Optional[List[str]] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.notes_session.create_note(
        title=title, content=content, notebook_id=notebook_id, tags=tags,
    )


@mcp.tool
async def update_note(nid: str, session_id: str,
                      title: Optional[str] = None,
                      content: Optional[str] = None,
                      notebook_id: Optional[str] = None,
                      tags: Optional[List[str]] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.notes_session.update_note(
        nid=nid, title=title, content=content,
        notebook_id=notebook_id, tags=tags,
    )


@mcp.tool
async def delete_note(nid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.notes_session.delete_note(nid)


@mcp.tool
async def pin_note(nid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.notes_session.pin_note(nid)


@mcp.tool
async def unpin_note(nid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.notes_session.unpin_note(nid)


@mcp.tool
async def archive_note(nid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.notes_session.archive_note(nid)


@mcp.tool
async def unarchive_note(nid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.notes_session.unarchive_note(nid)


@mcp.tool
async def add_tag(nid: str, tag: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.notes_session.add_tag(nid, tag)


@mcp.tool
async def remove_tag(nid: str, tag: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.notes_session.remove_tag(nid, tag)


@mcp.tool
async def search_notes(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.notes_session.search_notes(query)


@mcp.tool
async def list_recent(session_id: str, limit: int = 5):
    session, err = get_session(session_id)
    if err: return err
    return session.notes_session.list_recent(limit=limit)


@mcp.tool
async def list_pinned(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.notes_session.list_pinned()


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.notes_session.get_stats()
