from typing import Dict, Optional
from fastmcp import FastMCP
try:
    from session import LightPodcastSession
except ImportError:
    from software.LightPodcast.session import LightPodcastSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightPodcast")

session_dict: Dict[str, LightPodcastSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightPodcastSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.podcast_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.podcast_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_podcasts(session_id: str, category: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.podcast_session.list_podcasts(category=category)


@mcp.tool
async def get_podcast(pid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.podcast_session.get_podcast(pid)


@mcp.tool
async def subscribe_podcast(podcast_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.podcast_session.subscribe_podcast(podcast_id)


@mcp.tool
async def unsubscribe_podcast(podcast_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.podcast_session.unsubscribe_podcast(podcast_id)


@mcp.tool
async def list_episodes(session_id: str, podcast_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.podcast_session.list_episodes(podcast_id=podcast_id)


@mcp.tool
async def get_episode(eid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.podcast_session.get_episode(eid)


@mcp.tool
async def search_episodes(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.podcast_session.search_episodes(query)


@mcp.tool
async def list_queue(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.podcast_session.list_queue()


@mcp.tool
async def add_to_queue(episode_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.podcast_session.add_to_queue(episode_id)


@mcp.tool
async def remove_from_queue(qid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.podcast_session.remove_from_queue(qid)


@mcp.tool
async def reorder_queue(qid: str, position: int, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.podcast_session.reorder_queue(qid, position)


@mcp.tool
async def list_progress(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.podcast_session.list_progress()


@mcp.tool
async def update_progress(episode_id: str, seconds_played: int, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.podcast_session.update_progress(episode_id, seconds_played)


@mcp.tool
async def mark_completed(episode_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.podcast_session.mark_completed(episode_id)


@mcp.tool
async def list_downloads(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.podcast_session.list_downloads()


@mcp.tool
async def download_episode(episode_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.podcast_session.download_episode(episode_id)


@mcp.tool
async def delete_download(did: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.podcast_session.delete_download(did)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.podcast_session.get_stats()
