from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightVaultSession
except ImportError:
    from software.LightVault.session import LightVaultSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightVault")

session_dict: Dict[str, LightVaultSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightVaultSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.vault_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.vault_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_entries(session_id: str, folder_id: Optional[str] = None, tag: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.vault_session.list_entries(folder_id=folder_id, tag=tag)


@mcp.tool
async def get_entry(entid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.vault_session.get_entry(entid)


@mcp.tool
async def create_entry(title: str, username: str, password: str, session_id: str,
                       url: str = "", notes: str = "",
                       tags: Optional[List[str]] = None,
                       folder_id: str = "fd_personal"):
    session, err = get_session(session_id)
    if err: return err
    return session.vault_session.create_entry(
        title=title, username=username, password=password,
        url=url, notes=notes, tags=tags, folder_id=folder_id,
    )


@mcp.tool
async def update_entry(entid: str, session_id: str,
                       title: Optional[str] = None,
                       username: Optional[str] = None,
                       password: Optional[str] = None,
                       url: Optional[str] = None,
                       notes: Optional[str] = None,
                       tags: Optional[List[str]] = None,
                       folder_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.vault_session.update_entry(
        entid=entid, title=title, username=username, password=password,
        url=url, notes=notes, tags=tags, folder_id=folder_id,
    )


@mcp.tool
async def delete_entry(entid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.vault_session.delete_entry(entid)


@mcp.tool
async def copy_password(entid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.vault_session.copy_password(entid)


@mcp.tool
async def mark_used(entid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.vault_session.mark_used(entid)


@mcp.tool
async def list_folders(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.vault_session.list_folders()


@mcp.tool
async def create_folder(name: str, session_id: str, color: str = "#888888"):
    session, err = get_session(session_id)
    if err: return err
    return session.vault_session.create_folder(name=name, color=color)


@mcp.tool
async def delete_folder(fdid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.vault_session.delete_folder(fdid)


@mcp.tool
async def list_shares(session_id: str, entry_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.vault_session.list_shares(entry_id=entry_id)


@mcp.tool
async def share_entry(entry_id: str, shared_with: str, session_id: str,
                      expires_at: str = "", can_edit: bool = False):
    session, err = get_session(session_id)
    if err: return err
    return session.vault_session.share_entry(
        entry_id=entry_id, shared_with=shared_with,
        expires_at=expires_at, can_edit=can_edit,
    )


@mcp.tool
async def revoke_share(shid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.vault_session.revoke_share(shid)


@mcp.tool
async def list_audit_logs(session_id: str, entry_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.vault_session.list_audit_logs(entry_id=entry_id)


@mcp.tool
async def search_entries(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.vault_session.search_entries(query)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.vault_session.get_stats()
