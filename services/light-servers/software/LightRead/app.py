from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightReadSession
except ImportError:
    from software.LightRead.session import LightReadSession
import logging, colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightRead")
session_dict: Dict[str, LightReadSession] = {}

def get_session(session_id: str):
    s = session_dict.get(session_id)
    if s is None: return None, {"status": "failed", "output": "session not found"}
    return s, None

@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    s = LightReadSession(os_cfg=os_cfg, seed=seed)
    session_dict[s.session_id] = s
    return {"status": "ok", "session_id": s.session_id, "session_info": {"status": "ok", "output": s.read_session.get_session_dict()}}

@mcp.tool
async def logout(session_id: str):
    s, err = get_session(session_id)
    if err: return err
    info = {"status": "ok", "output": s.read_session.get_session_dict()}
    del session_dict[session_id]
    return info

@mcp.tool
async def list_books(session_id: str, kind: Optional[str] = None):
    s, err = get_session(session_id)
    if err: return err
    return s.read_session.list_books(kind=kind)

@mcp.tool
async def get_book(bid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.read_session.get_book(bid)

@mcp.tool
async def add_book(title: str, author: str, session_id: str, kind: str = "book", total_pages: int = 100):
    s, err = get_session(session_id)
    if err: return err
    return s.read_session.add_book(title, author, kind, total_pages)

@mcp.tool
async def delete_book(bid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.read_session.delete_book(bid)

@mcp.tool
async def update_progress(bid: str, page: int, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.read_session.update_progress(bid, page)

@mcp.tool
async def list_bookmarks(session_id: str, book_id: Optional[str] = None):
    s, err = get_session(session_id)
    if err: return err
    return s.read_session.list_bookmarks(book_id)

@mcp.tool
async def add_bookmark(book_id: str, page: int, session_id: str, note: str = ""):
    s, err = get_session(session_id)
    if err: return err
    return s.read_session.add_bookmark(book_id, page, note)

@mcp.tool
async def delete_bookmark(kid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.read_session.delete_bookmark(kid)

@mcp.tool
async def list_highlights(session_id: str, book_id: Optional[str] = None):
    s, err = get_session(session_id)
    if err: return err
    return s.read_session.list_highlights(book_id)

@mcp.tool
async def add_highlight(book_id: str, page: int, text: str, session_id: str, color: str = "yellow"):
    s, err = get_session(session_id)
    if err: return err
    return s.read_session.add_highlight(book_id, page, text, color)

@mcp.tool
async def delete_highlight(hid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.read_session.delete_highlight(hid)

@mcp.tool
async def search(query: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.read_session.search(query)

@mcp.tool
async def get_stats(session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.read_session.get_stats()
