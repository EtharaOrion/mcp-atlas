from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightTaxSession
except ImportError:
    from software.LightTax.session import LightTaxSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightTax")

session_dict: Dict[str, LightTaxSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightTaxSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.tax_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.tax_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_filings(session_id: str, status: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.tax_session.list_filings(status=status)


@mcp.tool
async def get_filing(fid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.tax_session.get_filing(fid)


@mcp.tool
async def create_filing(tax_year: int, filing_status: str, session_id: str,
                        gross_income: float = 0.0):
    session, err = get_session(session_id)
    if err: return err
    return session.tax_session.create_filing(
        tax_year=tax_year, filing_status=filing_status, gross_income=gross_income
    )


@mcp.tool
async def update_filing(fid: str, session_id: str,
                        filing_status: Optional[str] = None,
                        gross_income: Optional[float] = None,
                        tax_owed: Optional[float] = None,
                        refund: Optional[float] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.tax_session.update_filing(
        fid=fid, filing_status=filing_status, gross_income=gross_income,
        tax_owed=tax_owed, refund=refund,
    )


@mcp.tool
async def delete_filing(fid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.tax_session.delete_filing(fid)


@mcp.tool
async def submit_filing(fid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.tax_session.submit_filing(fid)


@mcp.tool
async def amend_filing(fid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.tax_session.amend_filing(fid)


@mcp.tool
async def list_deductions(session_id: str,
                          filing_id: Optional[str] = None,
                          category: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.tax_session.list_deductions(filing_id=filing_id, category=category)


@mcp.tool
async def add_deduction(filing_id: str, category: str, amount: float, session_id: str,
                        description: str = "", date: str = "", receipt_ref: str = ""):
    session, err = get_session(session_id)
    if err: return err
    return session.tax_session.add_deduction(
        filing_id=filing_id, category=category, amount=amount,
        description=description, date=date, receipt_ref=receipt_ref,
    )


@mcp.tool
async def update_deduction(did: str, session_id: str,
                           category: Optional[str] = None,
                           amount: Optional[float] = None,
                           description: Optional[str] = None,
                           date: Optional[str] = None,
                           receipt_ref: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.tax_session.update_deduction(
        did=did, category=category, amount=amount,
        description=description, date=date, receipt_ref=receipt_ref,
    )


@mcp.tool
async def delete_deduction(did: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.tax_session.delete_deduction(did)


@mcp.tool
async def list_income_sources(session_id: str, filing_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.tax_session.list_income_sources(filing_id=filing_id)


@mcp.tool
async def add_income_source(filing_id: str, source_type: str,
                            employer_or_payer: str, amount: float, session_id: str,
                            withheld: float = 0.0):
    session, err = get_session(session_id)
    if err: return err
    return session.tax_session.add_income_source(
        filing_id=filing_id, source_type=source_type,
        employer_or_payer=employer_or_payer, amount=amount, withheld=withheld,
    )


@mcp.tool
async def update_income_source(isid: str, session_id: str,
                               source_type: Optional[str] = None,
                               employer_or_payer: Optional[str] = None,
                               amount: Optional[float] = None,
                               withheld: Optional[float] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.tax_session.update_income_source(
        isid=isid, source_type=source_type,
        employer_or_payer=employer_or_payer, amount=amount, withheld=withheld,
    )


@mcp.tool
async def get_filing_summary(fid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.tax_session.get_filing_summary(fid)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.tax_session.get_stats()
