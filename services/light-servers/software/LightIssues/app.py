from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightIssuesSession
except ImportError:
    from software.LightIssues.session import LightIssuesSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightIssues")

session_dict: Dict[str, LightIssuesSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightIssuesSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.issues_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.issues_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_issues(session_id: str,
                      status: Optional[str] = None,
                      priority: Optional[str] = None,
                      assignee: Optional[str] = None,
                      sprint_id: Optional[str] = None,
                      tag: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.list_issues(
        status=status, priority=priority, assignee=assignee,
        sprint_id=sprint_id, tag=tag,
    )


@mcp.tool
async def get_issue(iid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.get_issue(iid)


@mcp.tool
async def create_issue(title: str, session_id: str,
                       description: str = "",
                       priority: str = "medium",
                       issue_type: str = "task",
                       assignee: Optional[str] = None,
                       reporter: str = "self",
                       sprint_id: Optional[str] = None,
                       tags: Optional[List[str]] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.create_issue(
        title=title, description=description, priority=priority,
        issue_type=issue_type, assignee=assignee, reporter=reporter,
        sprint_id=sprint_id, tags=tags,
    )


@mcp.tool
async def update_issue(iid: str, session_id: str,
                       title: Optional[str] = None,
                       description: Optional[str] = None,
                       status: Optional[str] = None,
                       priority: Optional[str] = None,
                       issue_type: Optional[str] = None,
                       assignee: Optional[str] = None,
                       sprint_id: Optional[str] = None,
                       tags: Optional[List[str]] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.update_issue(
        iid=iid, title=title, description=description, status=status,
        priority=priority, issue_type=issue_type, assignee=assignee,
        sprint_id=sprint_id, tags=tags,
    )


@mcp.tool
async def delete_issue(iid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.delete_issue(iid)


@mcp.tool
async def assign_issue(iid: str, assignee: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.assign_issue(iid, assignee)


@mcp.tool
async def change_status(iid: str, status: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.change_status(iid, status)


@mcp.tool
async def change_priority(iid: str, priority: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.change_priority(iid, priority)


@mcp.tool
async def add_to_sprint(iid: str, sid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.add_to_sprint(iid, sid)


@mcp.tool
async def remove_from_sprint(iid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.remove_from_sprint(iid)


@mcp.tool
async def list_sprints(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.list_sprints()


@mcp.tool
async def get_sprint(sid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.get_sprint(sid)


@mcp.tool
async def create_sprint(name: str, start_date: str, end_date: str, session_id: str,
                        goal: str = ""):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.create_sprint(
        name=name, start_date=start_date, end_date=end_date, goal=goal,
    )


@mcp.tool
async def start_sprint(sid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.start_sprint(sid)


@mcp.tool
async def close_sprint(sid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.close_sprint(sid)


@mcp.tool
async def list_by_sprint(sid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.list_by_sprint(sid)


@mcp.tool
async def add_comment(iid: str, author: str, text: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.add_comment(iid, author, text)


@mcp.tool
async def list_comments(iid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.list_comments(iid)


@mcp.tool
async def search_issues(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.search_issues(query)


@mcp.tool
async def list_backlog(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.list_backlog()


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.issues_session.get_stats()
