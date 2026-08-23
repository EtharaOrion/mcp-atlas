from typing import Dict, Optional
from fastmcp import FastMCP
try:
    from session import LightVideoSession
except ImportError:
    from software.LightVideo.session import LightVideoSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightVideo")

session_dict: Dict[str, LightVideoSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightVideoSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.video_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.video_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_videos(session_id: str, category: Optional[str] = None, channel: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.video_session.list_videos(category=category, channel=channel)


@mcp.tool
async def get_video(vid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.video_session.get_video(vid)


@mcp.tool
async def search_videos(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.video_session.search_videos(query)


@mcp.tool
async def list_playlists(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.video_session.list_playlists()


@mcp.tool
async def get_playlist(plid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.video_session.get_playlist(plid)


@mcp.tool
async def create_playlist(name: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.video_session.create_playlist(name)


@mcp.tool
async def delete_playlist(plid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.video_session.delete_playlist(plid)


@mcp.tool
async def add_to_playlist(plid: str, vid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.video_session.add_to_playlist(plid, vid)


@mcp.tool
async def remove_from_playlist(plid: str, vid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.video_session.remove_from_playlist(plid, vid)


@mcp.tool
async def list_watch_history(session_id: str, limit: int = 20):
    session, err = get_session(session_id)
    if err: return err
    return session.video_session.list_watch_history(limit=limit)


@mcp.tool
async def record_watch(vid: str, progress_seconds: int, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.video_session.record_watch(vid, progress_seconds)


@mcp.tool
async def clear_history(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.video_session.clear_history()


@mcp.tool
async def list_subscriptions(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.video_session.list_subscriptions()


@mcp.tool
async def subscribe(channel: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.video_session.subscribe(channel)


@mcp.tool
async def unsubscribe(channel: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.video_session.unsubscribe(channel)


@mcp.tool
async def like_video(vid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.video_session.like_video(vid)


@mcp.tool
async def get_recommended(session_id: str, limit: int = 5):
    session, err = get_session(session_id)
    if err: return err
    return session.video_session.get_recommended(limit=limit)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.video_session.get_stats()
