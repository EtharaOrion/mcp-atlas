from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightCRMSession
except ImportError:
    from software.LightCRM.session import LightCRMSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightCRM")

session_dict: Dict[str, LightCRMSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightCRMSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.crm_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.crm_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_contacts(session_id: str, tag: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.crm_session.list_contacts(tag=tag)


@mcp.tool
async def get_contact(cid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.crm_session.get_contact(cid)


@mcp.tool
async def create_contact(name: str, email: str, session_id: str,
                         phone: str = "", company: str = "",
                         title: str = "", tags: Optional[List[str]] = None,
                         notes: str = ""):
    session, err = get_session(session_id)
    if err: return err
    return session.crm_session.create_contact(
        name=name, email=email, phone=phone, company=company,
        title=title, tags=tags, notes=notes,
    )


@mcp.tool
async def update_contact(cid: str, session_id: str,
                         name: Optional[str] = None,
                         email: Optional[str] = None,
                         phone: Optional[str] = None,
                         company: Optional[str] = None,
                         title: Optional[str] = None,
                         tags: Optional[List[str]] = None,
                         notes: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.crm_session.update_contact(
        cid=cid, name=name, email=email, phone=phone,
        company=company, title=title, tags=tags, notes=notes,
    )


@mcp.tool
async def delete_contact(cid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.crm_session.delete_contact(cid)


@mcp.tool
async def list_deals(session_id: str,
                     stage: Optional[str] = None,
                     contact_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.crm_session.list_deals(stage=stage, contact_id=contact_id)


@mcp.tool
async def get_deal(did: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.crm_session.get_deal(did)


@mcp.tool
async def create_deal(title: str, contact_id: str, session_id: str,
                      stage: str = "lead",
                      amount: float = 0.0,
                      close_date: str = "",
                      notes: str = ""):
    session, err = get_session(session_id)
    if err: return err
    return session.crm_session.create_deal(
        title=title, contact_id=contact_id, stage=stage,
        amount=amount, close_date=close_date, notes=notes,
    )


@mcp.tool
async def update_deal(did: str, session_id: str,
                      title: Optional[str] = None,
                      contact_id: Optional[str] = None,
                      stage: Optional[str] = None,
                      amount: Optional[float] = None,
                      close_date: Optional[str] = None,
                      notes: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.crm_session.update_deal(
        did=did, title=title, contact_id=contact_id, stage=stage,
        amount=amount, close_date=close_date, notes=notes,
    )


@mcp.tool
async def delete_deal(did: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.crm_session.delete_deal(did)


@mcp.tool
async def move_stage(did: str, stage: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.crm_session.move_stage(did, stage)


@mcp.tool
async def search_contacts(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.crm_session.search_contacts(query)


@mcp.tool
async def list_won(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.crm_session.list_won()


@mcp.tool
async def list_lost(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.crm_session.list_lost()


@mcp.tool
async def get_pipeline_summary(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.crm_session.get_pipeline_summary()


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.crm_session.get_stats()
