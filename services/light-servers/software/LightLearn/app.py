from typing import Dict, Optional
from fastmcp import FastMCP
try:
    from session import LightLearnSession
except ImportError:
    from software.LightLearn.session import LightLearnSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightLearn")

session_dict: Dict[str, LightLearnSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightLearnSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.learn_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.learn_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_courses(session_id: str,
                       category: Optional[str] = None,
                       level: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.learn_session.list_courses(category=category, level=level)


@mcp.tool
async def get_course(cid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.learn_session.get_course(cid)


@mcp.tool
async def enroll(course_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.learn_session.enroll(course_id)


@mcp.tool
async def unenroll(course_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.learn_session.unenroll(course_id)


@mcp.tool
async def list_lessons(course_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.learn_session.list_lessons(course_id)


@mcp.tool
async def get_lesson(lsid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.learn_session.get_lesson(lsid)


@mcp.tool
async def complete_lesson(lesson_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.learn_session.complete_lesson(lesson_id)


@mcp.tool
async def list_enrollments(session_id: str, is_completed: Optional[bool] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.learn_session.list_enrollments(is_completed=is_completed)


@mcp.tool
async def get_enrollment(course_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.learn_session.get_enrollment(course_id)


@mcp.tool
async def update_progress(course_id: str, progress_percent: int, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.learn_session.update_progress(
        course_id=course_id, progress_percent=progress_percent,
    )


@mcp.tool
async def list_quizzes(session_id: str, lesson_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.learn_session.list_quizzes(lesson_id=lesson_id)


@mcp.tool
async def get_quiz(qzid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.learn_session.get_quiz(qzid)


@mcp.tool
async def submit_quiz(quiz_id: str, selected_index: int, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.learn_session.submit_quiz(
        quiz_id=quiz_id, selected_index=selected_index,
    )


@mcp.tool
async def list_quiz_attempts(session_id: str, quiz_id: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.learn_session.list_quiz_attempts(quiz_id=quiz_id)


@mcp.tool
async def search_courses(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.learn_session.search_courses(query)


@mcp.tool
async def list_finished(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.learn_session.list_finished()


@mcp.tool
async def get_course_progress(course_id: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.learn_session.get_course_progress(course_id)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.learn_session.get_stats()
