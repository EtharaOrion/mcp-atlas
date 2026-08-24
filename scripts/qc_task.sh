#!/usr/bin/env bash
# Usage: scripts/qc_task.sh <task-dir>
# Exit 0 = all checks pass, exit 1 = one or more failures.
set -uo pipefail

TASK="${1:?Usage: scripts/qc_task.sh <task-dir>}"
TASK="$(cd "$TASK" && pwd)"
SLUG="$(basename "$TASK")"
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
if command -v harbor &>/dev/null; then
    CFG=$(harbor run --print-config --path "$TASK" 2>/dev/null || true)
    if echo "$CFG" | python3 -c "
import sys, json
data = sys.stdin.read().strip()
c = json.loads(data) if data else {}
sys.exit(0 if len(c.get('tasks', [])) > 0 else 1)
" 2>/dev/null; then
        ok "Harbor classifies as task"
    else
        fail "Harbor sees this as a dataset — check task.toml (name must be org/name, schema_version required)"
    fi
else
    warn "harbor CLI not found — skipping Harbor classification check"
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
            fail "Image NOT found locally: $img  →  docker pull $img"
        fi
    done < <(grep -E '^\s+image\s*:' "$COMPOSE" | sed 's/.*image\s*:\s*//')
fi

sect "light-servers config"
if [[ -f "$COMPOSE" ]]; then
    if grep -q 'light-servers' "$COMPOSE" 2>/dev/null; then
        if grep -q 'ENABLED_SERVERS' "$COMPOSE" 2>/dev/null; then
            val=$(grep 'ENABLED_SERVERS' "$COMPOSE" | head -1 | sed 's/.*ENABLED_SERVERS[: ]*//' | tr -d '"' | xargs)
            ok "ENABLED_SERVERS: $val"
        else
            fail "light-servers used but ENABLED_SERVERS not set — will start ALL 161 servers (OOM risk)"
        fi
    else
        ok "Not using light-servers"
    fi
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
