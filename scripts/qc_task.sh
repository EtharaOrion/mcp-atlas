#!/usr/bin/env bash
# Usage: scripts/qc_task.sh <task-dir>
# Exit 0 = all checks pass, exit 1 = one or more failures.
set -uo pipefail

TASK="${1:?Usage: scripts/qc_task.sh <task-dir>}"
TASK="$(cd "$TASK" && pwd)"
SLUG="$(basename "$TASK")"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
FAIL=0

ok()   { printf "  [PASS] %s\n" "$*"; }
fail() { printf "  [FAIL] %s\n" "$*"; FAIL=$((FAIL+1)); }
warn() { printf "  [WARN] %s\n" "$*"; }
sect() { printf "\n── %s ──\n" "$*"; }

printf "QC: %s\n" "$SLUG"

sect "Structure"
for f in task.toml instruction.md environment/docker-compose.yaml tests/test.sh; do
    [[ -f "$TASK/$f" ]] && ok "$f" || fail "$f MISSING"
done
[[ -f "$TASK/solution/solve.sh" ]] && ok "solution/solve.sh" || warn "solution/solve.sh missing (optional)"

sect "task.toml"
if [[ -f "$TASK/task.toml" ]]; then
    QC_TASK="$TASK" python3 - <<'PYEOF'
import os, sys, re, pathlib

task_dir = os.environ["QC_TASK"]
text = pathlib.Path(task_dir + "/task.toml").read_text()
failed = False

def ok(msg):   print(f"  [PASS] {msg}")
def fail(msg): print(f"  [FAIL] {msg}"); global failed; failed = True

m = re.search(r'^name\s*=\s*"([^"]+)"', text, re.MULTILINE)
if m:
    if '/' in m.group(1): ok(f"name = {m.group(1)!r}")
    else: fail(f"name must be org/name format, got {m.group(1)!r}")
else:
    fail("name field missing")

if re.search(r'^schema_version', text, re.MULTILINE): ok("schema_version present")
else: fail("schema_version missing")

floats = re.findall(r'timeout_sec\s*=\s*(\d+\.\d+)', text)
if floats: fail(f"timeout_sec must be int (not float): {floats}")
else: ok("timeout_sec values are integers")

if 'CLAUDE_CODE_OAUTH_TOKEN' in text: ok("CLAUDE_CODE_OAUTH_TOKEN in verifier.env")
else: fail("CLAUDE_CODE_OAUTH_TOKEN missing from [verifier.env]")

bad = re.findall(r'url\s*=\s*"http://localhost[^"]*"', text)
if bad: fail(f"MCP URLs use localhost (must use Docker service names): {bad}")
else: ok("MCP server URLs use Docker service names")

if re.search(r'environment_mode\s*=\s*"separate"', text):
    if not (pathlib.Path(task_dir) / "tests" / "Dockerfile").exists():
        fail('environment_mode="separate" requires tests/Dockerfile — will crash at runtime')

sys.exit(1 if failed else 0)
PYEOF
    [[ $? -eq 0 ]] || FAIL=$((FAIL+1))
fi

sect "Harbor"
# Harbor distinguishes a task from a dataset by which manifest the directory
# carries: dataset.toml (harbor/models/dataset/paths.py: MANIFEST_FILENAME)
# marks a dataset, task.toml marks a task. Check that structurally — there is
# no cheap CLI probe for it. `harbor check` exists but spawns an LLM evaluator
# against a rubric, which is too slow and costly for a pre-flight script.
if [[ -f "$TASK/dataset.toml" ]]; then
    fail "dataset.toml present — Harbor will classify this as a dataset, not a task"
elif [[ -f "$TASK/task.toml" ]]; then
    ok "Harbor classifies as task (task.toml, no dataset.toml)"
else
    fail "neither task.toml nor dataset.toml — Harbor cannot classify this directory"
fi
if command -v harbor &>/dev/null; then
    ok "harbor CLI available ($(harbor --version 2>/dev/null | tr -d '\n'))"
else
    warn "harbor CLI not found — task cannot be run locally"
fi

sect "Docker images"
COMPOSE="$TASK/environment/docker-compose.yaml"
if [[ -f "$COMPOSE" ]]; then
    while IFS= read -r img; do
        img="${img//\'/}"; img="${img//\"/}"; img="$(echo "$img" | xargs)"
        [[ -z "$img" ]] && continue
        if docker image inspect "$img" &>/dev/null; then
            ok "Image present: $img"
        else
            # Images built out of this checkout are in no registry, so the
            # remedy is a build, not a pull -- `docker pull light-servers:latest`
            # only ever answers "repository does not exist".
            ctx="$REPO/services/${img%%:*}"
            if [[ -f "$ctx/Dockerfile" ]]; then
                warn "Image not built yet: $img  →  run_task.sh preflight builds it from $ctx"
            else
                warn "Image NOT found locally: $img  →  run_task.sh preflight pulls it"
            fi
        fi
    done < <(grep -E '^\s+image\s*:' "$COMPOSE" | sed 's/.*image\s*:\s*//')
fi

sect "tests/test.sh"
TESTSH="$TASK/tests/test.sh"
if [[ -f "$TESTSH" ]]; then
    grep -q 'from benchmark import' "$TESTSH" 2>/dev/null \
        && fail "Has 'from benchmark import' (yuji-harness specific — unavailable in harness)" \
        || ok "No yuji-harness benchmark imports"

    grep -q 'uv run' "$TESTSH" 2>/dev/null \
        && fail "Uses 'uv run' — main container has no uv, use python3 directly" \
        || ok "No 'uv run'"

    grep -q 'etype' "$TESTSH" 2>/dev/null \
        && ok "Has stream-json trajectory parser" \
        || warn "No trajectory parser in test.sh (tests may not see tool calls)"

    [[ -x "$TESTSH" ]] && ok "test.sh is executable" || fail "test.sh not executable (chmod +x tests/test.sh)"
fi

sect "Python syntax"
while IFS= read -r pyf; do
    if python3 -m py_compile "$pyf" 2>/dev/null; then
        ok "$(basename "$pyf")"
    else
        fail "Syntax error in $(basename "$pyf")"
        python3 -m py_compile "$pyf" 2>&1 | sed 's/^/        /'
    fi
done < <(find "$TASK/tests" -name "*.py" 2>/dev/null | sort)

printf "\n═══════════════════════════════════\n"
if [[ $FAIL -eq 0 ]]; then
    printf "  QC PASSED — %s is ready to run\n" "$SLUG"
else
    printf "  QC FAILED — %d issue(s) found\n" "$FAIL"
fi
printf "═══════════════════════════════════\n"
[[ $FAIL -eq 0 ]]
