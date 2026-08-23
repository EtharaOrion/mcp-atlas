from typing import Dict, Optional
from fastmcp import FastMCP
try:
    from session import LightMedSession
except ImportError:
    from software.LightMed.session import LightMedSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightMed")

session_dict: Dict[str, LightMedSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightMedSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.med_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.med_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_prescriptions(session_id: str,
                             status: Optional[str] = None,
                             dea_schedule: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.med_session.list_prescriptions(status=status, dea_schedule=dea_schedule)


@mcp.tool
async def get_prescription(rxid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.med_session.get_prescription(rxid)


@mcp.tool
async def add_prescription(medication_name: str, dosage: str, frequency: str,
                           quantity: int, refills_remaining: int, prescribed_by: str,
                           prescribed_on: str, expires_on: str, session_id: str,
                           dea_schedule: str = "non_controlled"):
    session, err = get_session(session_id)
    if err: return err
    return session.med_session.add_prescription(
        medication_name=medication_name, dosage=dosage, frequency=frequency,
        quantity=quantity, refills_remaining=refills_remaining,
        prescribed_by=prescribed_by, prescribed_on=prescribed_on,
        expires_on=expires_on, dea_schedule=dea_schedule,
    )


@mcp.tool
async def update_prescription(rxid: str, session_id: str,
                              dosage: Optional[str] = None,
                              frequency: Optional[str] = None,
                              quantity: Optional[int] = None,
                              refills_remaining: Optional[int] = None,
                              expires_on: Optional[str] = None,
                              status: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.med_session.update_prescription(
        rxid=rxid, dosage=dosage, frequency=frequency,
        quantity=quantity, refills_remaining=refills_remaining,
        expires_on=expires_on, status=status,
    )


@mcp.tool
async def cancel_prescription(rxid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.med_session.cancel_prescription(rxid)


@mcp.tool
async def list_refills(session_id: str,
                       prescription_id: Optional[str] = None,
                       status: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.med_session.list_refills(prescription_id=prescription_id, status=status)


@mcp.tool
async def request_refill(prescription_id: str, pharmacy_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.med_session.request_refill(
        prescription_id=prescription_id, pharmacy_id=pharmacy_id,
    )


@mcp.tool
async def fill_refill(refid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.med_session.fill_refill(refid)


@mcp.tool
async def reject_refill(refid: str, reason: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.med_session.reject_refill(refid=refid, reason=reason)


@mcp.tool
async def list_pharmacies(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.med_session.list_pharmacies()


@mcp.tool
async def get_pharmacy(phid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.med_session.get_pharmacy(phid)


@mcp.tool
async def add_pharmacy(name: str, address: str, phone: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.med_session.add_pharmacy(name=name, address=address, phone=phone)


@mcp.tool
async def list_audit_logs(session_id: str, prescription_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.med_session.list_audit_logs(prescription_id=prescription_id)


@mcp.tool
async def search_prescriptions(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.med_session.search_prescriptions(query)


@mcp.tool
async def get_controlled_substances(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.med_session.get_controlled_substances()


@mcp.tool
async def get_expiring_soon(session_id: str, days: int = 30, today: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.med_session.get_expiring_soon(days=days, today=today)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.med_session.get_stats()
