from typing import Dict, List, Any
from fastmcp import FastMCP
try:
    from session import LightGoogleMapsSession
except ImportError:
    from software.LightGoogleMaps.session import LightGoogleMapsSession
import logging
import colorlog

LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


mcp = FastMCP("google-maps")

session_dict: Dict[str, LightGoogleMapsSession] = {}


def get_session(session_id: str):
	session = session_dict.get(session_id)
	if session is None:
		return None, {"status": "failed", "output": "session not found"}
	return session, None


@mcp.tool
async def login(os_cfg: Dict[str, str], seed: int | None = None):
	session = LightGoogleMapsSession(os_cfg=os_cfg, seed=seed)
	session_dict[session.session_id] = session
	logger.info(f"A new user logged in! [{session.session_id}]")
	return {
		"status": "ok",
		"session_id": session.session_id,
		"session_info": {
			"status": "ok",
			"output": {}
        }
    }


@mcp.tool
async def logout(session_id: str | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	del session_dict[session_id]
	logger.info(f"A user logged out! [{session_id}]")
	return {
        "status": "ok",
        "output": session.google_maps_session.get_session_dict(),
    }


@mcp.tool
async def text_search(query: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.google_maps_session.text_search(query)


@mcp.tool
async def place_details(place_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.google_maps_session.place_details(place_id)


@mcp.tool
async def nearby_search(location: str, session_id: str, radius: int = 5000, place_type: str | None = None):
	session, err = get_session(session_id)
	if err:
		return err
	return session.google_maps_session.nearby_search(location, radius, place_type)


@mcp.tool
async def geocode(address: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.google_maps_session.geocode(address)


@mcp.tool
async def directions(origin: str, destination: str, session_id: str, mode: str = "driving"):
	session, err = get_session(session_id)
	if err:
		return err
	return session.google_maps_session.directions(origin, destination, mode)


@mcp.tool
async def distance_matrix(origins: List[str], destinations: List[str], session_id: str, mode: str = "driving"):
	session, err = get_session(session_id)
	if err:
		return err
	return session.google_maps_session.distance_matrix(origins, destinations, mode)

@mcp.tool
async def save_place(place_id: str, session_id: str, label: str = ""):
	session, err = get_session(session_id)
	if err:
		return err
	return session.google_maps_session.save_place(place_id, label)


@mcp.tool
async def list_saved_places(session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.google_maps_session.list_saved_places()


@mcp.tool
async def delete_saved_place(place_id: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.google_maps_session.delete_saved_place(place_id)


@mcp.tool
async def update_saved_place(place_id: str, label: str, session_id: str):
	session, err = get_session(session_id)
	if err:
		return err
	return session.google_maps_session.update_saved_place(place_id, label)
