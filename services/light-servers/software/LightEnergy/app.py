from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightEnergySession
except ImportError:
    from software.LightEnergy.session import LightEnergySession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightEnergy")

session_dict: Dict[str, LightEnergySession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightEnergySession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.energy_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.energy_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_meters(session_id: str, kind: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.energy_session.list_meters(kind=kind)


@mcp.tool
async def get_meter(mid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.energy_session.get_meter(mid)


@mcp.tool
async def add_meter(name: str, kind: str, session_id: str,
                    current_reading: float = 0.0,
                    currency_rate_per_unit: float = 0.0):
    session, err = get_session(session_id)
    if err: return err
    return session.energy_session.add_meter(
        name=name, kind=kind,
        current_reading=current_reading,
        currency_rate_per_unit=currency_rate_per_unit,
    )


@mcp.tool
async def list_readings(session_id: str,
                        meter_id: Optional[str] = None,
                        start_date: Optional[str] = None,
                        end_date: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.energy_session.list_readings(
        meter_id=meter_id, start_date=start_date, end_date=end_date,
    )


@mcp.tool
async def record_reading(meter_id: str, value: float, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.energy_session.record_reading(meter_id=meter_id, value=value)


@mcp.tool
async def get_latest_reading(mid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.energy_session.get_latest_reading(mid)


@mcp.tool
async def get_usage(meter_id: str, session_id: str,
                    start_date: Optional[str] = None,
                    end_date: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.energy_session.get_usage(
        meter_id=meter_id, start_date=start_date, end_date=end_date,
    )


@mcp.tool
async def list_bills(session_id: str,
                     meter_id: Optional[str] = None,
                     status: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.energy_session.list_bills(meter_id=meter_id, status=status)


@mcp.tool
async def get_bill(bill_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.energy_session.get_bill(bill_id)


@mcp.tool
async def generate_bill(meter_id: str, period_start: str, period_end: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.energy_session.generate_bill(
        meter_id=meter_id, period_start=period_start, period_end=period_end,
    )


@mcp.tool
async def pay_bill(bill_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.energy_session.pay_bill(bill_id)


@mcp.tool
async def list_alerts(session_id: str, is_active: Optional[bool] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.energy_session.list_alerts(is_active=is_active)


@mcp.tool
async def create_alert(meter_id: str, threshold: float, kind: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.energy_session.create_alert(
        meter_id=meter_id, threshold=threshold, kind=kind,
    )


@mcp.tool
async def toggle_alert(aid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.energy_session.toggle_alert(aid)


@mcp.tool
async def compare_periods(meter_id: str,
                          period_a_start: str, period_a_end: str,
                          period_b_start: str, period_b_end: str,
                          session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.energy_session.compare_periods(
        meter_id=meter_id,
        period_a_start=period_a_start, period_a_end=period_a_end,
        period_b_start=period_b_start, period_b_end=period_b_end,
    )


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.energy_session.get_stats()


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=9036)
