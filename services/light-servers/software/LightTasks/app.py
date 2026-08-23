from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightTasksSession
except ImportError:
    from software.LightTasks.session import LightTasksSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightTasks")

session_dict: Dict[str, LightTasksSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightTasksSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.tasks_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.tasks_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_projects(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.tasks_session.list_projects()


@mcp.tool
async def create_project(name: str, session_id: str, color: str = "#888888", description: str = ""):
    session, err = get_session(session_id)
    if err: return err
    return session.tasks_session.create_project(name=name, color=color, description=description)


@mcp.tool
async def delete_project(pid: str, session_id: str, reassign_to: str = "proj_inbox"):
    session, err = get_session(session_id)
    if err: return err
    return session.tasks_session.delete_project(pid=pid, reassign_to=reassign_to)


@mcp.tool
async def list_tasks(session_id: str,
                     project_id: Optional[str] = None,
                     status: Optional[str] = None,
                     priority: Optional[str] = None,
                     tag: Optional[str] = None,
                     assignee: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.tasks_session.list_tasks(
        project_id=project_id, status=status, priority=priority,
        tag=tag, assignee=assignee,
    )


@mcp.tool
async def get_task(tid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.tasks_session.get_task(tid)


@mcp.tool
async def create_task(title: str, session_id: str,
                      project_id: str = "proj_inbox",
                      priority: str = "medium",
                      due_date: str = "",
                      description: str = "",
                      tags: Optional[List[str]] = None,
                      assignee: str = "self"):
    session, err = get_session(session_id)
    if err: return err
    return session.tasks_session.create_task(
        title=title, project_id=project_id, priority=priority,
        due_date=due_date, description=description, tags=tags, assignee=assignee,
    )


@mcp.tool
async def update_task(tid: str, session_id: str,
                      title: Optional[str] = None,
                      description: Optional[str] = None,
                      status: Optional[str] = None,
                      priority: Optional[str] = None,
                      due_date: Optional[str] = None,
                      project_id: Optional[str] = None,
                      assignee: Optional[str] = None,
                      tags: Optional[List[str]] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.tasks_session.update_task(
        tid=tid, title=title, description=description, status=status,
        priority=priority, due_date=due_date, project_id=project_id,
        assignee=assignee, tags=tags,
    )


@mcp.tool
async def delete_task(tid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.tasks_session.delete_task(tid)


@mcp.tool
async def complete_task(tid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.tasks_session.complete_task(tid)


@mcp.tool
async def reopen_task(tid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.tasks_session.reopen_task(tid)


@mcp.tool
async def move_task(tid: str, project_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.tasks_session.move_task(tid, project_id)


@mcp.tool
async def add_tag(tid: str, tag: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.tasks_session.add_tag(tid, tag)


@mcp.tool
async def remove_tag(tid: str, tag: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.tasks_session.remove_tag(tid, tag)


@mcp.tool
async def search_tasks(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.tasks_session.search_tasks(query)


@mcp.tool
async def list_upcoming(session_id: str, days: int = 7, today: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.tasks_session.list_upcoming(days=days, today=today)


@mcp.tool
async def list_overdue(session_id: str, today: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.tasks_session.list_overdue(today=today)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.tasks_session.get_stats()
