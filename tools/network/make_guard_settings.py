#!/usr/bin/env python3
"""Build the Claude Code --settings file that carries the egress guard.

    tools/network/make_guard_settings.py <egress_rules.py> <out.json>

Called by scripts/run_task.sh, which passes the result to harbor as
`--ak config=<out.json>`. Harbor uploads it to
/tmp/claude-code-settings/settings.json inside the container and runs the CLI
with `--settings` pointed at it (harbor/agents/installed/claude_code.py:86,
:1875).

WHAT IT PRODUCES

A PreToolUse hook whose `command` is the whole of egress_rules.py, base64'd and
piped into python3. That is deliberate and the alternatives are worse:

  a bind mount     every bundle's docker-compose.yaml would need the same mount
                   added, and the overlay cannot supply one without knowing the
                   repo's host path.
  a file written   an agent running as root could overwrite it. The hook command
  into the image   is read out of settings.json at CLI startup, so once the run
                   is going there is nothing left on disk to tamper with.
  a second copy    two files spelling out "what counts as egress" drift, and the
  of the rules     drift is silent until a run is discarded for something the
                   hook let through.

base64 rather than a heredoc or an escaped literal: the payload then contains no
quote, newline, or backslash, so it survives JSON encoding, the shell, and
harbor's own upload without a single escaping question.

WHY THE MATCHER LISTS THE WEB TOOLS TOO

They are usually already gone -- run_task.sh passes --disallowedTools
WebSearch,WebFetch under isolation, so they never reach the tool list. The
matcher names them anyway so that a run configured without that flag (a hand
`harbor run`, DISALLOWED_TOOLS set empty) still refuses them rather than
silently allowing what the other layer was carrying.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

# Tools the hook is asked to judge. A regex over tool names, matched by Claude
# Code against each call before it runs.
MATCHER = "Bash|WebFetch|WebSearch"

# Generous, because the cost of the two failure modes is not symmetric: a hook
# that times out is skipped, and a skipped hook is a command that runs. The
# guard itself is a few milliseconds of regex over one string, so this only ever
# has to cover a cold interpreter start.
TIMEOUT_SEC = 15


def build(guard: Path) -> dict:
    blob = base64.b64encode(guard.read_bytes()).decode("ascii")
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": MATCHER,
                    "hooks": [
                        {
                            "type": "command",
                            # Command substitution, NOT a pipe into `python3 -`.
                            # The hook's own JSON payload arrives on stdin and
                            # egress_rules.main() reads it there, so stdin is
                            # not available to carry the program as well;
                            # `python3 -c "$(...)"` puts the program in argv and
                            # leaves fd 0 alone.
                            #
                            # No temp file either, so there is nothing on disk
                            # for an agent running as root to rewrite between
                            # one Bash call and the next.
                            #
                            # The single quotes are safe unconditionally:
                            # base64's alphabet is [A-Za-z0-9+/=] and contains
                            # no quote, backslash or newline.
                            "command": (
                                f"python3 -c \"$(printf %s '{blob}' | base64 -d)\""
                            ),
                            "timeout": TIMEOUT_SEC,
                        }
                    ],
                }
            ]
        }
    }


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        return 2
    guard, out = Path(argv[0]), Path(argv[1])
    if not guard.is_file():
        print(f"egress guard not found: {guard}", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(guard), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
