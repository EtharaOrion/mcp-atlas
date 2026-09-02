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

sect "Grading baselines"
# tests/old_env.json and tests/gt_env.json are DERIVED artefacts: they describe
# the world the light-servers corpus produces at this task's seed. Edit the
# shared corpus -- or mount corpus additions -- and they stop describing the
# served world, at which point a perfect run is graded against a world that no
# longer exists. Both channels break, in different ways:
#   * an ADDED entity is in the end dump but not in gt_env  -> `unexpected`
#     -> completion (Rc) scores 0.0
#   * a CHANGED entity is in both end and old_env but differs -> `drifted`
#     -> misbehave (Rb) rises above 0.0
# scripts/rederive_env.py rebuilds both from the live corpus; a non-zero exit
# here means they need rebuilding.
if [[ -f "$TASK/tests/oracle.json" && -f "$TASK/tests/old_env.json" ]]; then
    REDERIVE="$(dirname "${BASH_SOURCE[0]}")/rederive_env.py"
    if [[ -f "$REDERIVE" ]]; then
        OUT="$(python3 "$REDERIVE" "$TASK" 2>&1)"
        if grep -q "DIFFERS from committed" <<<"$OUT"; then
            fail "baselines do not match the corpus the servers now serve"
            grep -E "changed:|only in " <<<"$OUT" | sed 's/\[rederive\]/       /' | head -12
            printf "         fix: python3 scripts/rederive_env.py %s --write\n" "$TASK"
        elif grep -q "matches committed" <<<"$OUT"; then
            ok "old_env.json / gt_env.json match the live corpus"
        else
            warn "could not verify baselines (light-servers deps missing?)"
        fi
    else
        warn "scripts/rederive_env.py not found — baselines unverified"
    fi
else
    ok "No state-channel baselines to verify"
fi

sect "Corpus additions"
# Additions must never ship inside the bundle: anything inside it changes
# task_hash and breaks the memory/crucible_view.yaml binding.
if compgen -G "$TASK/corpus_additions/*" >/dev/null 2>&1; then
    fail "corpus_additions/ inside the bundle — changes task_hash; keep it outside"
else
    ok "No corpus additions inside the bundle"
fi
if [[ -f "$COMPOSE" ]] && grep -q 'COMPLEXMCP_CORPUS_ADDITIONS' "$COMPOSE" 2>/dev/null; then
    if grep -q 'COMPLEXMCP_SEED_MODE:\s*"seed"' "$COMPOSE" 2>/dev/null; then
        ok "additions mounted with seed mode"
    else
        fail "COMPLEXMCP_CORPUS_ADDITIONS set but seed mode is not \"seed\" — additions would be ignored"
    fi
    if grep -q 'COMPLEXMCP_WORLD_DATA' "$COMPOSE" 2>/dev/null; then
        fail "COMPLEXMCP_CORPUS_ADDITIONS and COMPLEXMCP_WORLD_DATA both set — hydrate() wipes the additions"
    fi
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
