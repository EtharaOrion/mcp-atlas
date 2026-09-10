#!/usr/bin/env bash
# Stage the judge credential, then hand every argument through to
# rubric_judge_cli.py unchanged -- the CLI contract is the container contract.
#
# The credential arrives as a READ-ONLY bind of the host's ~/.codex/auth.json
# at /codex-cred/auth.json. It is COPIED rather than used in place because
# `codex exec` rewrites auth.json whenever it refreshes its OAuth token;
# against a read-only mount that write fails and takes the judge call with it.
# The copy is writable, lives only in the container, and dies with it -- so a
# judge run can never modify or corrupt the operator's credential on the host.
# The cost is that a token refreshed in here is discarded; the host refreshes
# it again on its next use, which is why nothing depends on it persisting.
set -euo pipefail

mkdir -p "$CODEX_HOME"
cp /opt/rubric-judge/config.toml "$CODEX_HOME/config.toml"

if [ -r /codex-cred/auth.json ]; then
  cp /codex-cred/auth.json "$CODEX_HOME/auth.json"
  chmod 600 "$CODEX_HOME/auth.json"
else
  # Not fatal here: a Claude-model run needs no codex credential at all, and
  # rubric_judge_cli.py's own preflight prints a better-targeted message than
  # this script could. Failing loudly at the right layer beats failing here.
  echo "[rubric-judge] no credential at /codex-cred/auth.json --" >&2
  echo "               a codex model will fail its login preflight." >&2
fi

exec python3 /harness/scoring/rubric_judge_cli.py "$@"
