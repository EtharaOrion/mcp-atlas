from typing import Dict, List, Optional
from fastmcp import FastMCP
try:
    from session import LightFitnessSession
except ImportError:
    from software.LightFitness.session import LightFitnessSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

mcp = FastMCP("LightFitness")

session_dict: Dict[str, LightFitnessSession] = {}


def get_session(session_id: str):
    session = session_dict.get(session_id)
    if session is None:
        return None, {"status": "failed", "output": "session not found"}
    return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
    session = LightFitnessSession(os_cfg=os_cfg, seed=seed)
    session_dict[session.session_id] = session
    logger.info(f"A new user logged in! [{session.session_id}]")
    return {
        "status": "ok",
        "session_id": session.session_id,
        "session_info": {
            "status": "ok",
            "output": session.fitness_session.get_session_dict(),
        },
    }


@mcp.tool
async def logout(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    session_info = {
        "status": "ok",
        "output": session.fitness_session.get_session_dict(),
    }
    del session_dict[session_id]
    logger.info(f"A user logged out! [{session_id}]")
    return session_info


@mcp.tool
async def list_exercises(session_id: str,
                         muscle_group: Optional[str] = None,
                         kind: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.fitness_session.list_exercises(muscle_group=muscle_group, kind=kind)


@mcp.tool
async def get_exercise(exid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.fitness_session.get_exercise(exid)


@mcp.tool
async def add_exercise(name: str, muscle_group: str, kind: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.fitness_session.add_exercise(name=name, muscle_group=muscle_group, kind=kind)


@mcp.tool
async def list_workouts(session_id: str,
                        start_date: Optional[str] = None,
                        end_date: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.fitness_session.list_workouts(start_date=start_date, end_date=end_date)


@mcp.tool
async def get_workout(wkid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.fitness_session.get_workout(wkid)


@mcp.tool
async def create_workout(name: str, date: str, duration_min: int, session_id: str,
                         sets: Optional[List[Dict]] = None, notes: str = ""):
    session, err = get_session(session_id)
    if err: return err
    return session.fitness_session.create_workout(
        name=name, date=date, duration_min=duration_min, sets=sets, notes=notes,
    )


@mcp.tool
async def update_workout(wkid: str, session_id: str,
                         name: Optional[str] = None,
                         date: Optional[str] = None,
                         duration_min: Optional[int] = None,
                         notes: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.fitness_session.update_workout(
        wkid=wkid, name=name, date=date, duration_min=duration_min, notes=notes,
    )


@mcp.tool
async def delete_workout(wkid: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.fitness_session.delete_workout(wkid)


@mcp.tool
async def add_set(wkid: str, exid: str, session_id: str,
                  reps: int = 0, weight_kg: float = 0.0,
                  distance_km: float = 0.0, duration_sec: int = 0):
    session, err = get_session(session_id)
    if err: return err
    return session.fitness_session.add_set(
        wkid=wkid, exid=exid, reps=reps,
        weight_kg=weight_kg, distance_km=distance_km, duration_sec=duration_sec,
    )


@mcp.tool
async def list_prs(session_id: str, exid: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.fitness_session.list_prs(exid=exid)


@mcp.tool
async def record_pr(exid: str, kind: str, value: float, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.fitness_session.record_pr(exid=exid, kind=kind, value=value)


@mcp.tool
async def list_weekly_stats(session_id: str, limit: int = 10):
    session, err = get_session(session_id)
    if err: return err
    return session.fitness_session.list_weekly_stats(limit=limit)


@mcp.tool
async def compute_weekly_stats(week_start_date: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.fitness_session.compute_weekly_stats(week_start_date)


@mcp.tool
async def get_muscle_group_frequency(session_id: str,
                                     start_date: Optional[str] = None,
                                     end_date: Optional[str] = None):
    session, err = get_session(session_id)
    if err: return err
    return session.fitness_session.get_muscle_group_frequency(
        start_date=start_date, end_date=end_date,
    )


@mcp.tool
async def search_exercises(query: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.fitness_session.search_exercises(query)


@mcp.tool
async def get_stats(session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.fitness_session.get_stats()


@mcp.tool
async def get_calendar(month: str, session_id: str):
    session, err = get_session(session_id)
    if err: return err
    return session.fitness_session.get_calendar(month)
