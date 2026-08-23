import datetime
import json
import random
from pathlib import Path

from software.utils.world_snapshot import restore_into, seed_mode, resolve_seed

CORPUS_PATH = Path(__file__).resolve().parent / "corpus"

class ClockSession:
    def __init__(self, seed=None):
        # Seedless: clock state (frozen `_now` + post-init rng) is loaded from a
        # snapshot beside this module; `seed` accepted for client compat, ignored.
        if seed_mode():
            # Seed architecture: world rolled from a seed (re-armed).
            self.rng = random.Random(resolve_seed(seed))
            # World data loaded verbatim from corpus/state.json (no cooking):
            # the clock's starting time is authored, not randomly rolled. A
            # per-task $COMPLEXMCP_WORLD_DATA/LightSystem.json {"now": ...}
            # overrides it, so scenario worlds whose entities live at another
            # date (e.g. the SHPA Jan-2026 bundles) can pin a matching clock.
            with open(CORPUS_PATH / "state.json") as _f:
                now_str = json.load(_f)["now"]
            from software.utils.world_data import active_dir
            _d = active_dir()
            if _d:
                _p = Path(_d) / "LightSystem.json"
                if _p.is_file():
                    with open(_p) as _f:
                        now_str = json.load(_f).get("now", now_str)
            self._now = datetime.datetime.strptime(now_str, "%Y-%m-%d %H:%M:%S")
        else:
            # Seedless: world loaded verbatim from the frozen snapshot.
            restore_into(self, Path(__file__).resolve().parent / "clock_world.pkl")
    
    def now(self):
        return {
            "status": "ok",
            "output": str(self._now)
        }
    
    def step(self):
        self._now += datetime.timedelta(seconds=self.rng.randint(1, 10))
        return self.now()

    def _init_now(self, year: int = 2026) -> datetime.datetime:
        start = datetime.datetime(year, 1, 1, 0, 0, 0)
        next_year = datetime.datetime(year + 1, 1, 1, 0, 0, 0)
        seconds_in_year = int((next_year - start).total_seconds())
        offset = self.rng.randrange(seconds_in_year)

        return start + datetime.timedelta(seconds=offset)
    
    def gen_past(self, start_year: int = 2015, k: int = 1) -> list[str]:
        if k <= 0:
            return []
        start = datetime.datetime(start_year, 1, 1, 0, 0, 0)
        end = self._now
        if start >= end:
            return [str(end)] * k

        seconds_range = int((end - start).total_seconds())
        timestamps = []
        for _ in range(k):
            offset = self.rng.randrange(seconds_range + 1)
            timestamps.append(start + datetime.timedelta(seconds=offset))

        timestamps.sort()
        return {
            "status": "ok",
            "output": [str(ts) for ts in timestamps]
        }


if __name__ == "__main__":
    clock_session = ClockSession(seed=1)

    print(clock_session.now())
