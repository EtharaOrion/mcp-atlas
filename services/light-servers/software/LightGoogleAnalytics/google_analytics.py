import random
from typing import Dict, List, Any
from pathlib import Path
import sys
from datetime import datetime

WORK_DIR = Path('.').__str__()
if WORK_DIR not in sys.path:
    sys.path.append(WORK_DIR)

from software.utils import corpus_registry
from software.utils.core import OSConnector, DummyOSConnector, connect_os
from software.utils.world_snapshot import restore_into, seed_mode, resolve_seed
from software.utils.time import TimeMachine

CORPUS_PATH = Path(__file__).resolve().parent / "corpus"


def _to_int(v, default=0) -> int:
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return default
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


class GoogleAnalyticsSession:
    """Deterministic sandbox for the Google Analytics (GA4 Data API) mock, ported from the FastAPI service.

    State is loaded from the corpus at init; subsequent calls read the in-memory
    tables so repeated calls within a session stay consistent.
    """

    _DIMENSIONS = ["date", "country", "pagePath", "deviceCategory"]
    _REALTIME_DIMENSIONS = ["country", "deviceCategory", "unifiedScreenName"]
    _METRICS = ["sessions", "activeUsers", "screenPageViews", "eventCount"]
    _REALTIME_METRICS = ["activeUsers", "eventCount"]

    def __init__(self, os_cfg, seed=None):
        # Seedless: world loaded verbatim from a frozen snapshot next to
        # this module; `seed` is accepted for client compat and ignored.
        if seed_mode():
            # Seed architecture: world rolled from a seed (re-armed).
            self.rng = random.Random(resolve_seed(seed))
            self.os = connect_os(os_cfg)
            self.time_machine = TimeMachine(rng=self.rng)

            info = corpus_registry.load(CORPUS_PATH / "google_analytics.yaml")

            self.events: List[Dict[str, Any]] = [
                {
                    **{d: r.get(d) for d in self._DIMENSIONS},
                    **{m: _to_int(r.get(m), 0) for m in self._METRICS},
                }
                for r in info.get("events", [])
            ]
            self.realtime: List[Dict[str, Any]] = [
                {
                    **{d: r.get(d) for d in self._REALTIME_DIMENSIONS},
                    **{m: _to_int(r.get(m), 0) for m in self._REALTIME_METRICS},
                }
                for r in info.get("realtime", [])
            ]
            self.property: Dict[str, Any] = dict(info.get("property", {}))
            from software.utils.world_data import hydrate as _hydrate_world_data
            _hydrate_world_data(self, 'LightGoogleAnalytics')
        else:
            # Seedless: world loaded verbatim from the frozen snapshot.
            restore_into(self, Path(__file__).resolve().parent / "world.pkl")
            self.os = connect_os(os_cfg)

    def get_session_dict(self):
        return {"events": self.events, "realtime": self.realtime}

    # --- helpers -----------------------------------------------------------
    def _now(self) -> str:
        return self.os.now()

    def uuid(self) -> str:
        alphabet = "0123456789"
        return ''.join(self.rng.choices(alphabet, k=16))

    def _aggregate(self, source_rows, dimensions, metrics, available_dims, available_metrics):
        dims = [d for d in dimensions if d in available_dims]
        mets = [m for m in metrics if m in available_metrics]
        if not mets:
            mets = [available_metrics[0]]

        grouped = {}
        order = []
        for row in source_rows:
            key = tuple(row.get(d, "") for d in dims)
            if key not in grouped:
                grouped[key] = {m: 0 for m in mets}
                order.append(key)
            for m in mets:
                grouped[key][m] += _to_int(row.get(m, 0))

        rows = []
        for key in order:
            rows.append({
                "dimensionValues": [{"value": v} for v in key],
                "metricValues": [{"value": str(grouped[key][m])} for m in mets],
            })

        return {
            "dimensionHeaders": [{"name": d} for d in dims],
            "metricHeaders": [{"name": m, "type": "TYPE_INTEGER"} for m in mets],
            "rows": rows,
            "rowCount": len(rows),
        }

    def _names(self, items):
        out = []
        for item in items or []:
            if isinstance(item, dict):
                name = item.get("name")
                if name:
                    out.append(name)
            elif item:
                out.append(item)
        return out

    # --- API methods -------------------------------------------------------
    def run_report(self, property_id: str, dimensions: List[Any] | None = None,
                   metrics: List[Any] | None = None,
                   date_ranges: List[Any] | None = None) -> Dict[str, Any]:
        report = self._aggregate(
            self.events,
            self._names(dimensions),
            self._names(metrics),
            self._DIMENSIONS,
            self._METRICS,
        )
        report["kind"] = "analyticsData#runReport"
        if date_ranges:
            report["metadata"] = {"dateRanges": date_ranges}
        return {"status": "ok", "output": report}

    def run_realtime_report(self, property_id: str, dimensions: List[Any] | None = None,
                            metrics: List[Any] | None = None) -> Dict[str, Any]:
        report = self._aggregate(
            self.realtime,
            self._names(dimensions),
            self._names(metrics),
            self._REALTIME_DIMENSIONS,
            self._REALTIME_METRICS,
        )
        report["kind"] = "analyticsData#runRealtimeReport"
        return {"status": "ok", "output": report}

    def batch_run_reports(self, property_id: str, requests: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
        reports = []
        for req in requests or []:
            inner = self.run_report(
                property_id,
                dimensions=self._names(req.get("dimensions")),
                metrics=self._names(req.get("metrics")),
                date_ranges=req.get("dateRanges"),
            )
            reports.append(inner["output"])
        return {"status": "ok", "output": {"kind": "analyticsData#batchRunReports", "reports": reports}}

    def get_metadata(self, property_id: str) -> Dict[str, Any]:
        return {"status": "ok", "output": {
            "name": f"properties/{property_id}/metadata",
            "dimensions": [
                {"apiName": d, "uiName": d, "category": "Page / Screen" if d == "pagePath" else "General"}
                for d in self._DIMENSIONS
            ],
            "metrics": [
                {"apiName": m, "uiName": m, "type": "TYPE_INTEGER"}
                for m in self._METRICS
            ],
        }}

    def get_property(self) -> Dict[str, Any]:
        return {"status": "ok", "output": dict(self.property)}



    def create_saved_report(self, name: str, property_id: str, dimensions: List[Any] | None = None, metrics: List[Any] | None = None) -> Dict[str, Any]:
        if not hasattr(self, 'saved_reports'):
            self.saved_reports = []
        report_id = self.uuid()
        entry = {
            "report_id": report_id,
            "name": name,
            "property_id": property_id,
            "dimensions": dimensions or [],
            "metrics": metrics or [],
            "created_at": self._now(),
        }
        self.saved_reports.append(entry)
        return {"status": "ok", "output": entry}

    def list_saved_reports(self) -> Dict[str, Any]:
        if not hasattr(self, 'saved_reports'):
            self.saved_reports = []
        return {"status": "ok", "output": list(self.saved_reports)}

    def delete_saved_report(self, report_id: str) -> Dict[str, Any]:
        if not hasattr(self, 'saved_reports'):
            self.saved_reports = []
        before = len(self.saved_reports)
        self.saved_reports = [r for r in self.saved_reports if r["report_id"] != report_id]
        if len(self.saved_reports) == before:
            return {"status": "failed", "output": f"Saved report {report_id} not found"}
        return {"status": "ok", "output": {"deleted_report_id": report_id}}

    def update_saved_report(self, report_id: str, name: str | None = None, dimensions: List[Any] | None = None, metrics: List[Any] | None = None) -> Dict[str, Any]:
        if not hasattr(self, 'saved_reports'):
            self.saved_reports = []
        for r in self.saved_reports:
            if r["report_id"] == report_id:
                if name is not None:
                    r["name"] = name
                if dimensions is not None:
                    r["dimensions"] = dimensions
                if metrics is not None:
                    r["metrics"] = metrics
                return {"status": "ok", "output": r}
        return {"status": "failed", "output": f"Saved report {report_id} not found"}

if __name__ == "__main__":
    s = GoogleAnalyticsSession(seed=12)
    print(s.get_property())
    print(s.run_report("412233445", dimensions=["country"], metrics=["sessions"]))
