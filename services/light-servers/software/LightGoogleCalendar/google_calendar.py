import random
from typing import Dict, List, Any
from pathlib import Path
import yaml
import sys
from datetime import datetime

WORK_DIR = Path('.').__str__()
if WORK_DIR not in sys.path:
    sys.path.append(WORK_DIR)

from software.utils.core import OSConnector, DummyOSConnector
from software.utils.world_snapshot import restore_into, seed_mode, resolve_seed
from software.utils.time import TimeMachine

CORPUS_PATH = Path(__file__).resolve().parent / "corpus"


def _to_bool(v) -> bool:
    return str(v).strip().lower() == "true"


class GoogleCalendarSession:
    """Deterministic sandbox for the Google Calendar mock, ported from the FastAPI service.

    State is loaded from the corpus at init; subsequent calls read and mutate the
    in-memory tables so repeated calls within a session stay consistent.
    """

    def __init__(self, os_cfg, seed=None, fixture=None):
        # Seedless: world loaded verbatim from a frozen snapshot next to
        # this module; `seed` is accepted for client compat and ignored.
        if seed_mode():
            # Seed architecture: world rolled from a seed (re-armed).
            self.rng = random.Random(resolve_seed(seed))
            self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()
            self.time_machine = TimeMachine(rng=self.rng)

            with open(CORPUS_PATH / "google_calendar.yaml") as f:
                info = yaml.safe_load(f)

            self.calendars: List[Dict[str, Any]] = [
                {**c, "primary": _to_bool(c.get("primary", False))} for c in info.get("calendars", [])
            ]
            self.events: List[Dict[str, Any]] = []
            for e in info.get("events", []):
                # Corpus recurrence may be a single RRULE string or already a
                # list of RRULE strings; both must land flat, or recurring
                # events dump as [["RRULE:…"]] and the state diff charges
                # phantom misbehaviour against authored flat snapshots.
                recurrence = e.get("recurrence") or []
                if isinstance(recurrence, str):
                    recurrence = [recurrence]
                self.events.append({
                    **e,
                    "all_day": _to_bool(e.get("all_day", False)),
                    "recurrence": list(recurrence),
                })
            self.attendees: Dict[str, List[Dict[str, Any]]] = {}
            for r in info.get("event_attendees", []):
                self.attendees.setdefault(str(r.get("event_id")), []).append({
                    "email": r.get("email"),
                    "displayName": r.get("display_name"),
                    "responseStatus": r.get("response_status"),
                    "optional": _to_bool(r.get("optional", False)),
                    "organizer": _to_bool(r.get("organizer", False)),
                })

            from software.utils.fixtures import apply as _apply_fixtures
            _apply_fixtures(self, "LightGoogleCalendar", fixture)
            from software.utils.world_data import hydrate as _hydrate_world_data
            _hydrate_world_data(self, "LightGoogleCalendar")

            # Some authored worlds carry events but no `calendars` section,
            # leaving list_calendars() empty and "primary" unresolvable even
            # though every event names its calendar_id -- the calendar becomes
            # undiscoverable by any tool. Derive the calendar list from the
            # events' own calendar_ids (first-seen = primary) rather than
            # touching the authored corpus data. calendars is not part of
            # get_session_dict(), so this never shows up in the state diff.
            if not self.calendars and self.events:
                seen: List[str] = []
                for e in self.events:
                    cid = e.get("calendar_id")
                    if cid and cid not in seen:
                        seen.append(cid)
                self.calendars = [
                    {"id": cid, "summary": cid, "primary": i == 0}
                    for i, cid in enumerate(seen)
                ]
        else:
            # Seedless: world loaded verbatim from the frozen snapshot.
            restore_into(self, Path(__file__).resolve().parent / "world.pkl")
            self.os = OSConnector(session_id=os_cfg["session_id"], url=os_cfg["url"]) if os_cfg else DummyOSConnector()

    def get_session_dict(self):
        return {"events": self.events}

    # --- helpers -----------------------------------------------------------
    def _now(self) -> str:
        return self.os.now()

    def uuid(self) -> str:
        alphabet = "0123456789abcdef"
        return ''.join(self.rng.choices(alphabet, k=10))

    def _new_event_id(self) -> str:
        return f"evt-{self.uuid()}"

    def _resolve_calendar(self, calendar_id):
        if calendar_id == "primary":
            return next((c["id"] for c in self.calendars if c["primary"]), None)
        return calendar_id

    def _serialize_event(self, e):
        out = dict(e)
        out["start"] = {"dateTime": e["start"], "timeZone": "America/Los_Angeles"} if not e["all_day"] \
            else {"date": e["start"][:10]}
        out["end"] = {"dateTime": e["end"], "timeZone": "America/Los_Angeles"} if not e["all_day"] \
            else {"date": e["end"][:10]}
        out["attendees"] = self.attendees.get(e["id"], [])
        return out

    # --- Calendars ---------------------------------------------------------
    def list_calendars(self) -> Dict[str, Any]:
        return {"status": "ok", "output": {
            "kind": "calendar#calendarList", "items": list(self.calendars),
        }}

    def get_calendar(self, calendar_id: str) -> Dict[str, Any]:
        if calendar_id == "primary":
            calendar_id = next((c["id"] for c in self.calendars if c["primary"]), None)
        for c in self.calendars:
            if c["id"] == calendar_id:
                return {"status": "ok", "output": c}
        return {"status": "failed", "output": f"Calendar {calendar_id} not found"}

    # --- Events ------------------------------------------------------------
    def list_events(self, calendar_id: str, time_min: str | None = None, time_max: str | None = None,
                    q: str | None = None, single_events: bool = True, order_by: str = "startTime",
                    max_results: int = 25, page_token: str | None = None) -> Dict[str, Any]:
        resolved = self._resolve_calendar(calendar_id)
        if not resolved or not any(c["id"] == resolved for c in self.calendars):
            return {"status": "failed", "output": f"Calendar {calendar_id} not found"}
        results = [e for e in self.events if e["calendar_id"] == resolved]
        if time_min:
            results = [e for e in results if e["end"] >= time_min]
        if time_max:
            results = [e for e in results if e["start"] <= time_max]
        if q:
            ql = q.lower()
            results = [e for e in results
                       if ql in e["summary"].lower() or ql in (e["description"] or "").lower()
                       or ql in (e["location"] or "").lower()]
        if order_by == "startTime":
            results.sort(key=lambda e: e["start"])
        elif order_by == "updated":
            results.sort(key=lambda e: e.get("updated", e["start"]), reverse=True)
        try:
            offset = int(page_token or 0)
        except ValueError:
            offset = 0
        page = results[offset: offset + max_results]
        next_token = str(offset + max_results) if offset + max_results < len(results) else None
        return {"status": "ok", "output": {
            "kind": "calendar#events",
            "items": [self._serialize_event(e) for e in page],
            "nextPageToken": next_token,
        }}

    def get_event(self, calendar_id: str, event_id: str) -> Dict[str, Any]:
        resolved = self._resolve_calendar(calendar_id)
        for e in self.events:
            if e["calendar_id"] == resolved and e["id"] == event_id:
                return {"status": "ok", "output": self._serialize_event(e)}
        return {"status": "failed", "output": f"Event {event_id} not found"}

    def create_event(self, calendar_id: str, summary: str, start: Dict[str, Any], end: Dict[str, Any],
                     description: str = "", location: str = "",
                     attendees: List[Dict[str, Any]] | None = None,
                     recurrence: List[str] | None = None, visibility: str = "default") -> Dict[str, Any]:
        resolved = self._resolve_calendar(calendar_id)
        if not any(c["id"] == resolved for c in self.calendars):
            return {"status": "failed", "output": f"Calendar {calendar_id} not found"}
        start = start or {}
        end = end or {}
        all_day = "date" in start
        event = {
            "id": self._new_event_id(),
            "calendar_id": resolved,
            "summary": summary or "",
            "description": description or "",
            "location": location or "",
            "start": start.get("dateTime") or start.get("date") or self._now(),
            "end": end.get("dateTime") or end.get("date") or self._now(),
            "all_day": all_day,
            "status": "confirmed",
            # Was hardcoded to "amelia@orbit-labs.com" regardless of which
            # calendar the event was actually created on -- stamped the wrong
            # persona onto every event created for any other calendar_id
            # (e.g. a task's own amos.whitfield@Finthesiss.ai calendar).
            # The creator/organizer of a newly created event is the calendar
            # it was created on.
            "creator": resolved,
            "organizer": resolved,
            "recurrence": recurrence or [],
            "visibility": visibility or "default",
        }
        self.events.append(event)
        if attendees:
            self.attendees[event["id"]] = [{
                "email": a.get("email"),
                "displayName": a.get("displayName", ""),
                "responseStatus": a.get("responseStatus", "needsAction"),
                "optional": bool(a.get("optional", False)),
                "organizer": bool(a.get("organizer", False)),
            } for a in attendees]
        return {"status": "ok", "output": self._serialize_event(event)}

    def update_event(self, calendar_id: str, event_id: str, summary: str | None = None,
                     description: str | None = None, location: str | None = None,
                     start: Dict[str, Any] | None = None, end: Dict[str, Any] | None = None,
                     attendees: List[Dict[str, Any]] | None = None, status: str | None = None,
                     visibility: str | None = None) -> Dict[str, Any]:
        resolved = self._resolve_calendar(calendar_id)
        payload = {
            "summary": summary, "description": description, "location": location,
            "start": start, "end": end, "attendees": attendees,
            "status": status, "visibility": visibility,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        for i, e in enumerate(self.events):
            if e["calendar_id"] == resolved and e["id"] == event_id:
                for field in ("summary", "description", "location", "status", "visibility"):
                    if field in payload:
                        self.events[i][field] = payload[field]
                if "start" in payload:
                    s = payload["start"]
                    self.events[i]["start"] = s.get("dateTime") or s.get("date") or e["start"]
                    self.events[i]["all_day"] = "date" in s
                if "end" in payload:
                    en = payload["end"]
                    self.events[i]["end"] = en.get("dateTime") or en.get("date") or e["end"]
                if "attendees" in payload:
                    self.attendees[event_id] = [{
                        "email": a.get("email"),
                        "displayName": a.get("displayName", ""),
                        "responseStatus": a.get("responseStatus", "needsAction"),
                        "optional": bool(a.get("optional", False)),
                        "organizer": bool(a.get("organizer", False)),
                    } for a in payload["attendees"]]
                return {"status": "ok", "output": self._serialize_event(self.events[i])}
        return {"status": "failed", "output": f"Event {event_id} not found"}

    def delete_event(self, calendar_id: str, event_id: str) -> Dict[str, Any]:
        resolved = self._resolve_calendar(calendar_id)
        for i, e in enumerate(self.events):
            if e["calendar_id"] == resolved and e["id"] == event_id:
                self.events.pop(i)
                self.attendees.pop(event_id, None)
                return {"status": "ok", "output": {"deleted": True, "id": event_id}}
        return {"status": "failed", "output": f"Event {event_id} not found"}

    # --- Free/busy ---------------------------------------------------------
    def freebusy(self, time_min: str, time_max: str, calendar_ids: List[str]) -> Dict[str, Any]:
        calendars_block = {}
        for raw_id in calendar_ids:
            cid = self._resolve_calendar(raw_id)
            if not cid or not any(c["id"] == cid for c in self.calendars):
                calendars_block[raw_id] = {"errors": [{"reason": "notFound"}], "busy": []}
                continue
            busy = []
            for e in self.events:
                if e["calendar_id"] != cid:
                    continue
                if e["status"] != "confirmed":
                    continue
                if e["end"] < time_min or e["start"] > time_max:
                    continue
                busy.append({"start": e["start"], "end": e["end"]})
            calendars_block[raw_id] = {"busy": busy}
        return {"status": "ok", "output": {
            "kind": "calendar#freeBusy", "timeMin": time_min, "timeMax": time_max,
            "calendars": calendars_block,
        }}


if __name__ == "__main__":
    s = GoogleCalendarSession(seed=12)
    print(s.list_calendars())
    print(s.list_events("primary"))
