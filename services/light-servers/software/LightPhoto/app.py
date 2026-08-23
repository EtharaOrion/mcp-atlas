from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightPhotoSession
except ImportError:
    from software.LightPhoto.session import LightPhotoSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightPhoto")

session_dict: Dict[str, LightPhotoSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightPhotoSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.photo_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.photo_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_albums(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.photo_session.list_albums()


@mcp.tool
async def get_album(alid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.photo_session.get_album(alid)


@mcp.tool
async def create_album(name: str, session_id: str, description: str = ""):
    session, err = get_session(session_id)
    if err: return err
    return session.photo_session.create_album(name=name, description=description)


@mcp.tool
async def delete_album(alid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.photo_session.delete_album(alid)


@mcp.tool
async def update_album(alid: str, session_id: str,
                       name: Optional[str] = None,
                       description: Optional[str] = None,
                       cover_photo_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.photo_session.update_album(
        alid=alid, name=name, description=description, cover_photo_id=cover_photo_id
    )


@mcp.tool
async def list_photos(session_id: str,
                      album_id: Optional[str] = None,
                      tag: Optional[str] = None,
                      face_group_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.photo_session.list_photos(
        album_id=album_id, tag=tag, face_group_id=face_group_id
    )


@mcp.tool
async def get_photo(pid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.photo_session.get_photo(pid)


@mcp.tool
async def add_photo(album_id: str, title: str, filename: str, session_id: str,
                    taken_at: Optional[str] = None,
                    tags: Optional[List[str]] = None,
                    location: str = "",
                    exif: Optional[Dict[str, object]] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.photo_session.add_photo(
        album_id=album_id, title=title, filename=filename,
        taken_at=taken_at, tags=tags, location=location, exif=exif,
    )


@mcp.tool
async def delete_photo(pid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.photo_session.delete_photo(pid)


@mcp.tool
async def add_tag(pid: str, tag: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.photo_session.add_tag(pid, tag)


@mcp.tool
async def remove_tag(pid: str, tag: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.photo_session.remove_tag(pid, tag)


@mcp.tool
async def move_to_album(pid: str, album_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.photo_session.move_to_album(pid, album_id)


@mcp.tool
async def list_face_groups(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.photo_session.list_face_groups()


@mcp.tool
async def create_face_group(name: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.photo_session.create_face_group(name)


@mcp.tool
async def assign_face(pid: str, fgid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.photo_session.assign_face(pid, fgid)


@mcp.tool
async def create_share_link(album_id: str, expires_at: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.photo_session.create_share_link(album_id, expires_at)


@mcp.tool
async def list_share_links(session_id: str, album_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.photo_session.list_share_links(album_id=album_id)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.photo_session.get_stats()
