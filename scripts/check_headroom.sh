#!/usr/bin/env bash
# Verify the Headroom integration is installed correctly. Read-only.
#
# grader_compress fails open, so a broken install and a disabled one behave
# identically at run time. This script is the difference between the two.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
    if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
fi

fail=0
ok()   { printf '  ok    %s\n' "$1"; }
bad()  { printf '  FAIL  %s\n' "$1"; fail=1; }
note() { printf '  --    %s\n' "$1"; }

echo "Headroom integration check"
echo
echo "module"
if [ -f services/scoring/grader_compress.py ]; then
    ok "services/scoring/grader_compress.py present"
else
    bad "services/scoring/grader_compress.py missing"
fi
if (cd services/scoring && "$ROOT/$PY" -c "import grader_compress" 2>/dev/null) \
   || (cd services/scoring && python3 -c "import grader_compress" 2>/dev/null); then
    ok "imports cleanly with no headroom installed (the fail-open path)"
else
    bad "grader_compress does not import"
fi

echo
echo "call sites"
check_site() {
    if grep -q "$2" "$1"; then ok "$1"; else bad "$1 -- no '$2'"; fi
}
check_site services/scoring/rubric_judge_cli.py            "compress_evidence(model, traj_ctx)"
check_site services/scoring/rubric_judge.py                "compress_messages(model, messages)"
check_site services/diagnostics/single_model_diagnostic.py "compress_messages(self.config.model_name, messages)"

echo
echo "deliberate exclusions"
if grep -q "grader_compress" services/scoring/score_claims.py; then
    bad "score_claims.py is wired -- it judges the artifact, not evidence"
else
    ok "score_claims.py not wired (compresses the answer under judgement)"
fi
if grep -rq "grader_compress" services/agent-harness services/cc-bridge 2>/dev/null; then
    bad "agent path is wired -- see the cache_control interlock"
else
    ok "agent path not wired"
fi

echo
echo "library"
if "$PY" -c "import headroom" 2>/dev/null; then
    note "headroom importable on this host ($("$PY" -c "import headroom;print(getattr(headroom,'__version__','?'))" 2>/dev/null))"
else
    note "headroom NOT importable here -- expected; it only needs to exist in the"
    note "task image where the grader runs. Host-side graders (score_claims,"
    note "diagnostics) do need it locally to compress anything."
fi

echo
echo "enabled bundles"
found=0
for compose in tasks/*/environment/docker-compose.yaml; do
    [ -f "$compose" ] || continue
    if grep -q "GRADER_HEADROOM_ENABLED" "$compose"; then
        note "$(dirname "$(dirname "$compose")") -- flag set"
        found=1
        dockerfile="$(dirname "$compose")/Dockerfile"
        grep -q "headroom-ai" "$dockerfile" \
            || bad "$dockerfile has no headroom-ai -- flag set but nothing installed"
    fi
done
[ "$found" -eq 0 ] && note "none (default). Turn one on with scripts/enable_headroom.sh <task>"

echo
echo "tests"
if "$PY" -m pytest services/scoring/tests/test_grader_compress.py \
        services/scoring/tests/test_grader_compress_wiring.py -q >/dev/null 2>&1; then
    ok "grader_compress suites pass"
else
    bad "grader_compress suites fail -- run them for detail"
fi

echo
if [ "$fail" -eq 0 ]; then
    echo "Integration looks correct. It is still OFF unless a bundle sets"
    echo "GRADER_HEADROOM_ENABLED; see services/scoring/HEADROOM.md."
else
    echo "Integration is broken. Because everything fails open, a run would"
    echo "still grade -- just uncompressed and silently."
fi
exit "$fail"
