from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightForumSession
except ImportError:
    from software.LightForum.session import LightForumSession
import logging, colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightForum")
session_dict: Dict[str, LightForumSession] = {}

def get_session(session_id: str):
    s = session_dict.get(session_id)
    if s is None: return None, {"status": "failed", "output": "session not found"}
    return s, None

@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    s = LightForumSession(os_cfg=os_cfg, seed=seed)
    session_dict[s.session_id] = s
    return {"status": "ok", "session_id": s.session_id, "session_info": {"status": "ok", "output": s.forum_session.get_session_dict()}}

@mcp.tool
async def logout(session_id: str):
    s, err = get_session(session_id)
    if err: return err
    info = {"status": "ok", "output": s.forum_session.get_session_dict()}
    del session_dict[session_id]
    return info

@mcp.tool
async def list_subforums(session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.list_subforums()

@mcp.tool
async def create_subforum(name: str, session_id: str, description: str = ""):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.create_subforum(name, description)

@mcp.tool
async def delete_subforum(fid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.delete_subforum(fid)

@mcp.tool
async def list_threads(session_id: str, subforum_id: Optional[str] = None, pinned: Optional[bool] = None):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.list_threads(subforum_id, pinned)

@mcp.tool
async def get_thread(tid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.get_thread(tid)

@mcp.tool
async def create_thread(subforum_id: str, title: str, author: str, body: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.create_thread(subforum_id, title, author, body)

@mcp.tool
async def delete_thread(tid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.delete_thread(tid)

@mcp.tool
async def lock_thread(tid: str, session_id: str, locked: bool = True):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.lock_thread(tid, locked)

@mcp.tool
async def pin_thread(tid: str, session_id: str, pinned: bool = True):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.pin_thread(tid, pinned)

@mcp.tool
async def list_posts(thread_id: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.list_posts(thread_id)

@mcp.tool
async def add_post(thread_id: str, author: str, body: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.add_post(thread_id, author, body)

@mcp.tool
async def delete_post(pid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.delete_post(pid)

@mcp.tool
async def upvote_thread(tid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.upvote_thread(tid)

@mcp.tool
async def downvote_thread(tid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.downvote_thread(tid)

@mcp.tool
async def upvote_post(pid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.upvote_post(pid)

@mcp.tool
async def downvote_post(pid: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.downvote_post(pid)

@mcp.tool
async def search_threads(query: str, session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.search_threads(query)

@mcp.tool
async def top_threads(session_id: str, limit: int = 5):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.top_threads(limit=limit)

@mcp.tool
async def get_stats(session_id: str):
    s, err = get_session(session_id)
    if err: return err
    return s.forum_session.get_stats()
