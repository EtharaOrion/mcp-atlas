from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightGameSession
except ImportError:
    from software.LightGame.session import LightGameSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightGame")

session_dict: Dict[str, LightGameSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightGameSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.game_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.game_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_games(session_id: str,
                     platform: Optional[str] = None,
                     genre: Optional[str] = None,
                     is_installed: Optional[bool] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.game_session.list_games(
        platform=platform, genre=genre, is_installed=is_installed,
    )


@mcp.tool
async def get_game(gid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.game_session.get_game(gid)


@mcp.tool
async def add_game(title: str, session_id: str,
                   platform: str = "pc", genre: str = "action",
                   is_installed: bool = False):
    session, err = get_session(session_id)
    if err: return err
    return session.game_session.add_game(
        title=title, platform=platform, genre=genre, is_installed=is_installed,
    )


@mcp.tool
async def delete_game(gid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.game_session.delete_game(gid)


@mcp.tool
async def install_game(gid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.game_session.install_game(gid)


@mcp.tool
async def uninstall_game(gid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.game_session.uninstall_game(gid)


@mcp.tool
async def list_achievements(session_id: str,
                            game_id: Optional[str] = None,
                            is_unlocked: Optional[bool] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.game_session.list_achievements(
        game_id=game_id, is_unlocked=is_unlocked,
    )


@mcp.tool
async def unlock_achievement(achid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.game_session.unlock_achievement(achid)


@mcp.tool
async def list_play_sessions(session_id: str,
                             game_id: Optional[str] = None,
                             start_date: Optional[str] = None,
                             end_date: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.game_session.list_play_sessions(
        game_id=game_id, start_date=start_date, end_date=end_date,
    )


@mcp.tool
async def start_play(game_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.game_session.start_play(game_id)


@mcp.tool
async def end_play(psid: str, duration_minutes: int, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.game_session.end_play(psid=psid, duration_minutes=duration_minutes)


@mcp.tool
async def get_total_playtime(game_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.game_session.get_total_playtime(game_id)


@mcp.tool
async def list_wishlist(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.game_session.list_wishlist()


@mcp.tool
async def add_to_wishlist(title: str, session_id: str,
                          platform: str = "pc", price: float = 0.0):
    session, err = get_session(session_id)
    if err: return err
    return session.game_session.add_to_wishlist(
        title=title, platform=platform, price=price,
    )


@mcp.tool
async def remove_from_wishlist(wlid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.game_session.remove_from_wishlist(wlid)


@mcp.tool
async def search_games(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.game_session.search_games(query)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.game_session.get_stats()
