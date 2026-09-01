"""Boot gate for the corpus-additions layer (invariant I2).

Run as a process *before* any server starts:

    python -m software.utils.corpus_boot

Exits 0 when the configuration is coherent (including the common case where
the feature is off entirely), and non-zero with a message naming the app and
the key when it is not. ``entrypoint.sh`` runs this before launching any
``fastmcp run``, so a bad additions mount stops the container instead of
serving a subtly wrong world through a clean-looking boot.

Why a separate process rather than a check inside each app: the deployed
topology is one ``fastmcp run`` per app, so there is no single in-process
"before main.run()" moment that all 140 apps pass through. The aggregated
``server_main.py`` calls ``validate()`` directly for the same reason.
"""
from __future__ import annotations

import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from software.utils import corpus_registry  # noqa: E402


def validate(software_dir=None) -> list:
    """Validate + pre-build. Returns the apps that received additions."""
    software_dir = software_dir or (_APP_ROOT / "software")
    return corpus_registry.validate_all(software_dir)


def main(argv=None) -> int:
    try:
        touched = validate()
    except corpus_registry.CorpusAdditionsError as e:
        print(f"[corpus-additions] REFUSING TO START: {e}", file=sys.stderr, flush=True)
        return 2
    except Exception as e:  # malformed YAML, unreadable mount, ...
        print(f"[corpus-additions] REFUSING TO START: {type(e).__name__}: {e}",
              file=sys.stderr, flush=True)
        return 2
    if touched:
        print(f"[corpus-additions] applied to: {', '.join(touched)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
