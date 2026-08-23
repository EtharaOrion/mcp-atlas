from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightDriveSession
except ImportError:
    from software.LightDrive.session import LightDriveSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightDrive")

session_dict: Dict[str, LightDriveSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightDriveSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.drive_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.drive_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_folders(session_id: str, parent_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.list_folders(parent_id=parent_id)


@mcp.tool
async def get_folder(fdid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.get_folder(fdid)


@mcp.tool
async def create_folder(name: str, session_id: str, parent_id: str = "fd_root"):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.create_folder(name=name, parent_id=parent_id)


@mcp.tool
async def delete_folder(fdid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.delete_folder(fdid)


@mcp.tool
async def list_files(session_id: str, folder_id: Optional[str] = None,
                     is_trashed: Optional[bool] = None,
                     is_starred: Optional[bool] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.list_files(
        folder_id=folder_id, is_trashed=is_trashed, is_starred=is_starred,
    )


@mcp.tool
async def get_file(fid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.get_file(fid)


@mcp.tool
async def upload_file(name: str, session_id: str,
                      folder_id: str = "fd_root",
                      size_bytes: int = 0,
                      mime_type: str = "application/octet-stream"):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.upload_file(
        name=name, folder_id=folder_id,
        size_bytes=size_bytes, mime_type=mime_type,
    )


@mcp.tool
async def delete_file(fid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.delete_file(fid)


@mcp.tool
async def star_file(fid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.star_file(fid)


@mcp.tool
async def unstar_file(fid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.unstar_file(fid)


@mcp.tool
async def move_to_trash(fid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.move_to_trash(fid)


@mcp.tool
async def restore_from_trash(fid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.restore_from_trash(fid)


@mcp.tool
async def list_versions(file_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.list_versions(file_id)


@mcp.tool
async def create_version(file_id: str, session_id: str,
                         size_bytes: int = 0, comment: str = ""):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.create_version(
        file_id=file_id, size_bytes=size_bytes, comment=comment,
    )


@mcp.tool
async def rollback_version(file_id: str, version_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.rollback_version(file_id=file_id, version_id=version_id)


@mcp.tool
async def list_share_links(session_id: str,
                           target_kind: Optional[str] = None,
                           target_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.list_share_links(target_kind=target_kind, target_id=target_id)


@mcp.tool
async def create_share_link(target_kind: str, target_id: str, session_id: str,
                            can_edit: bool = False, expires_at: str = ""):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.create_share_link(
        target_kind=target_kind, target_id=target_id,
        can_edit=can_edit, expires_at=expires_at,
    )


@mcp.tool
async def search(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.search(query)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.drive_session.get_stats()
