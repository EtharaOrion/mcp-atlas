#!/usr/bin/env bash
# Turn grader-path Headroom compression on (or off) for one task bundle.
#
#   scripts/enable_headroom.sh tasks/<task>            # on
#   scripts/enable_headroom.sh tasks/<task> --disable  # off, byte-identical revert
#   scripts/enable_headroom.sh --all [--disable]
#
# Two edits are required and BOTH must land or it silently does nothing:
#   1. environment/Dockerfile        -- install headroom-ai in the grader image
#   2. environment/docker-compose.yaml -- set the flag on the `main` service,
#      which is where Harbor runs tests/test.sh and therefore the rubric judge
#
# Rebuild the task image afterwards, then confirm with:
#   grep grader_compress <run logs>
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PIN='"headroom-ai>=0.37,<0.38"'
FLAG='GRADER_HEADROOM_ENABLED'

targets=()
mode=enable
for arg in "$@"; do
    case "$arg" in
        --disable) mode=disable ;;
        --all)     for d in tasks/*/; do [ -f "$d/environment/docker-compose.yaml" ] && targets+=("${d%/}"); done ;;
        -*)        echo "unknown flag: $arg" >&2; exit 2 ;;
        *)         targets+=("${arg%/}") ;;
    esac
done

if [ "${#targets[@]}" -eq 0 ]; then
    sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
fi

for task in "${targets[@]}"; do
    PIN="$PIN" FLAG="$FLAG" MODE="$mode" TASK="$task" python3 <<'PYEOF'
import os
import pathlib
import re
import sys

task = pathlib.Path(os.environ["TASK"])
pin = os.environ["PIN"]
flag = os.environ["FLAG"]
enable = os.environ["MODE"] == "enable"

dockerfile = task / "environment" / "Dockerfile"
compose = task / "environment" / "docker-compose.yaml"
for path in (dockerfile, compose):
    if not path.is_file():
        sys.exit("{}: not a task bundle ({} missing)".format(task, path))

changed = []

# --- 1. Dockerfile: the grader's pip line ----------------------------------
src = dockerfile.read_text()
pip_lines = [ln for ln in src.splitlines() if re.match(r"RUN\s+pip\s+install", ln)]
if not pip_lines:
    sys.exit("{}: no `RUN pip install` line to extend".format(dockerfile))

for line in pip_lines:
    if enable and pin not in line:
        src = src.replace(line, line + " " + pin, 1)
        changed.append("{}: + {}".format(dockerfile, pin))
    elif not enable and pin in line:
        src = src.replace(line, line.replace(" " + pin, ""), 1)
        changed.append("{}: - {}".format(dockerfile, pin))
dockerfile.write_text(src)

# --- 2. compose: the flag on `main` ----------------------------------------
# Edited as text, not through a YAML round-trip: these files carry the
# harbor-canary header and hand-written comments explaining the SCORING_DIR
# mount, and a dump would erase every one of them.
src = compose.read_text()
entry = '      {}: "true"\n'.format(flag)

if enable:
    if flag not in src:
        m = re.search(r"^  main:\n", src, re.M)
        if not m:
            sys.exit("{}: no `main` service; that is where the verifier runs".format(compose))
        block = re.search(r"^    environment:\n", src[m.end():], re.M)
        nxt = re.search(r"^  \w[\w-]*:\n", src[m.end():], re.M)
        if block and (not nxt or block.start() < nxt.start()):
            at = m.end() + block.end()
            src = src[:at] + entry + src[at:]
        else:
            at = m.end()
            src = src[:at] + "    environment:\n" + entry + src[at:]
        changed.append("{}: + {}".format(compose, flag))
else:
    if flag in src:
        src = src.replace(entry, "")
        # Drop an environment: block we ourselves created and left empty. It is
        # empty exactly when the next line is not one of its children, i.e. is
        # indented no deeper than the key itself (or the file ends).
        src = re.sub(
            r"^    environment:\n(?= {4}\S| {2}\S|\Z)", "", src, flags=re.M
        )
        changed.append("{}: - {}".format(compose, flag))
compose.write_text(src)

if changed:
    for line in changed:
        print("  " + line)
else:
    print("  {}: already {}".format(task, "enabled" if enable else "disabled"))
PYEOF
done

echo
if [ "$mode" = enable ]; then
    echo "Rebuild the task image, run the task, then:"
    echo "    grep grader_compress <run logs>"
    echo "A missing log line means it is NOT running -- every failure path is silent."
else
    echo "Reverted. Rebuild the task image to drop headroom-ai from it."
fi
