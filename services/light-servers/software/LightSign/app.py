from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightSignSession
except ImportError:
    from software.LightSign.session import LightSignSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightSign")

session_dict: Dict[str, LightSignSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightSignSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.sign_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.sign_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_documents(session_id: str, status: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.sign_session.list_documents(status=status)


@mcp.tool
async def get_document(docid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.sign_session.get_document(docid)


@mcp.tool
async def upload_document(title: str, filename: str, session_id: str,
                          page_count: int = 1, uploaded_by: str = "self"):
    session, err = get_session(session_id)
    if err: return err
    return session.sign_session.upload_document(
        title=title, filename=filename,
        page_count=page_count, uploaded_by=uploaded_by,
    )


@mcp.tool
async def delete_document(docid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.sign_session.delete_document(docid)


@mcp.tool
async def send_for_signature(docid: str, signers: List[str], session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.sign_session.send_for_signature(docid=docid, signers=signers)


@mcp.tool
async def cancel_document(docid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.sign_session.cancel_document(docid)


@mcp.tool
async def list_signature_requests(session_id: str,
                                  document_id: Optional[str] = None,
                                  status: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.sign_session.list_signature_requests(
        document_id=document_id, status=status,
    )


@mcp.tool
async def get_signature_request(srid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.sign_session.get_signature_request(srid)


@mcp.tool
async def sign_document(request_id: str, page: int, x: int, y: int,
                        image_hash: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.sign_session.sign_document(
        request_id=request_id, page=page, x=x, y=y, image_hash=image_hash,
    )


@mcp.tool
async def decline_signature(request_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.sign_session.decline_signature(request_id)


@mcp.tool
async def list_signatures(session_id: str, document_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.sign_session.list_signatures(document_id=document_id)


@mcp.tool
async def list_audit(session_id: str, document_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.sign_session.list_audit(document_id=document_id)


@mcp.tool
async def record_audit(document_id: str, actor: str, action: str, session_id: str,
                       details: str = ""):
    session, err = get_session(session_id)
    if err: return err
    return session.sign_session.record_audit(
        document_id=document_id, actor=actor, action=action, details=details,
    )


@mcp.tool
async def list_pending_signatures(signer: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.sign_session.list_pending_signatures(signer)


@mcp.tool
async def search_documents(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.sign_session.search_documents(query)


@mcp.tool
async def list_completed(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.sign_session.list_completed()


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.sign_session.get_stats()
