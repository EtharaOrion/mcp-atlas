from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightHRSession
except ImportError:
    from software.LightHR.session import LightHRSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightHR")

session_dict: Dict[str, LightHRSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightHRSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.hr_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.hr_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_employees(session_id: str, department: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.hr_session.list_employees(department=department)


@mcp.tool
async def get_employee(eid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.hr_session.get_employee(eid)


@mcp.tool
async def create_employee(name: str, email: str, department: str, role: str, session_id: str,
                          hire_date: str = "",
                          manager_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.hr_session.create_employee(
        name=name, email=email, department=department, role=role,
        hire_date=hire_date, manager_id=manager_id,
    )


@mcp.tool
async def update_employee(eid: str, session_id: str,
                          name: Optional[str] = None,
                          email: Optional[str] = None,
                          department: Optional[str] = None,
                          role: Optional[str] = None,
                          hire_date: Optional[str] = None,
                          manager_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.hr_session.update_employee(
        eid=eid, name=name, email=email, department=department,
        role=role, hire_date=hire_date, manager_id=manager_id,
    )


@mcp.tool
async def terminate_employee(eid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.hr_session.terminate_employee(eid)


@mcp.tool
async def list_leaves(session_id: str,
                      employee_id: Optional[str] = None,
                      status: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.hr_session.list_leaves(employee_id=employee_id, status=status)


@mcp.tool
async def request_leave(employee_id: str, type: str,
                        start_date: str, end_date: str,
                        days: float, session_id: str,
                        reason: str = ""):
    session, err = get_session(session_id)
    if err: return err
    return session.hr_session.request_leave(
        employee_id=employee_id, type=type,
        start_date=start_date, end_date=end_date,
        days=days, reason=reason,
    )


@mcp.tool
async def approve_leave(lid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.hr_session.approve_leave(lid)


@mcp.tool
async def reject_leave(lid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.hr_session.reject_leave(lid)


@mcp.tool
async def list_pending_leaves(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.hr_session.list_pending_leaves()


@mcp.tool
async def list_timesheets(session_id: str,
                          employee_id: Optional[str] = None,
                          start_date: Optional[str] = None,
                          end_date: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.hr_session.list_timesheets(
        employee_id=employee_id, start_date=start_date, end_date=end_date,
    )


@mcp.tool
async def log_time(employee_id: str, date: str, hours: float,
                   project: str, session_id: str,
                   description: str = ""):
    session, err = get_session(session_id)
    if err: return err
    return session.hr_session.log_time(
        employee_id=employee_id, date=date, hours=hours,
        project=project, description=description,
    )


@mcp.tool
async def delete_time_entry(teid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.hr_session.delete_time_entry(teid)


@mcp.tool
async def get_employee_hours(employee_id: str, session_id: str,
                             start_date: Optional[str] = None,
                             end_date: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.hr_session.get_employee_hours(
        employee_id=employee_id, start_date=start_date, end_date=end_date,
    )


@mcp.tool
async def list_by_department(department: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.hr_session.list_by_department(department)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.hr_session.get_stats()
