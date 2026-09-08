#!/usr/bin/env bash
# Tear down the harness background services and reap Docker leftovers.
#
# Images and build cache are deliberately KEPT: they are the warm cache that
# makes a second run fast. This reaps only stopped containers and the volumes
# nothing is attached to.
#
#   bash scripts/stop_harness.sh [--dry-run] [--all] [--force]
#
#   --dry-run  print what would be killed/removed, change nothing
#   --all      blanket `docker container/volume prune` instead of the harness-
#              scoped sweep. Removes stopped containers from UNRELATED Docker
#              projects on this machine too.
#   --force    proceed even when a run looks live. Kills the model route out
#              from under it; the trial dies mid-flight.
set -uo pipefail

DRY=0; ALL=0; FORCE=0
for a in "$@"; do
  case "$a" in
    --dry-run|-n) DRY=1 ;;
    --all)        ALL=1 ;;
    --force)      FORCE=1 ;;
    -h|--help)    sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown flag: $a (want --dry-run|--all|--force)" >&2; exit 2 ;;
  esac
done

say()  { echo "[stop-harness] $*"; }
run()  { if [ "$DRY" = 1 ]; then echo "[dry-run]      $*"; else "$@"; fi; }

# Ports the harness binds. zbridge is shared by every concurrent run_task.sh on
# this machine, which is why the live-run guard below exists at all.
PORTS=(8766 4000 4001 8787 8788)

cmd_of()  { ps -o command= -p "$1" 2>/dev/null; }
ppid_of() { ps -o ppid= -p "$1" 2>/dev/null | tr -d ' '; }

# --- who is a service, who is only holding one ------------------------------
# `(nohup uv run … &)` leaves a 3-deep chain: an orphaned bash that still shows
# in pgrep as `bash scripts/run_task.sh <task>`, the `uv run` supervisor, and
# the real server. Only the last does any work; the other two are dead weight
# that makes it look like a run is still going.
SERVICE_PIDS=()
for pat in 'python -m zbridge' 'cbridge\.py' 'zbridge_adapter\.py' 'headroom.*proxy'; do
  while read -r p; do [ -n "$p" ] && SERVICE_PIDS+=("$p"); done < <(pgrep -f "$pat" 2>/dev/null)
done

# Ancestors worth reaping alongside a service: the `uv run` supervisor, and an
# orphaned run_task.sh (PPID 1 — its real parent already exited). A run_task.sh
# with a living parent is a REAL run and is never touched here.
WRAPPER_PIDS=()
for svc in "${SERVICE_PIDS[@]:-}"; do
  [ -n "${svc:-}" ] || continue
  p="$(ppid_of "$svc")"
  while [ -n "${p:-}" ] && [ "$p" -gt 1 ] 2>/dev/null; do
    c="$(cmd_of "$p")"
    case "$c" in
      *"uv run"*)        WRAPPER_PIDS+=("$p") ;;
      *run_task.sh*)     [ "$(ppid_of "$p")" = "1" ] && WRAPPER_PIDS+=("$p") ;;
    esac
    p="$(ppid_of "$p")"
  done
done

# --- live-run guard ----------------------------------------------------------
# A run_task.sh that is NOT one of the orphaned wrappers above, or a live
# `harbor run`, means a trial is in flight and shares these bridges.
LIVE=()
while read -r p; do
  [ -n "$p" ] || continue
  skip=0
  for w in "${WRAPPER_PIDS[@]:-}"; do [ "$p" = "$w" ] && skip=1; done
  [ "$skip" = 0 ] && LIVE+=("$p")
done < <(pgrep -f 'scripts/run_task.sh' 2>/dev/null)
while read -r p; do [ -n "$p" ] && LIVE+=("$p"); done < <(pgrep -f 'harbor run' 2>/dev/null)

if [ "${#LIVE[@]}" -gt 0 ] && [ "$FORCE" != 1 ]; then
  say "REFUSING: a run looks live. These bridges are shared machine-wide."
  for p in "${LIVE[@]}"; do echo "    $p  $(cmd_of "$p")"; done
  say "wait for it, or re-run with --force to kill it mid-trial."
  exit 1
fi
[ "${#LIVE[@]}" -gt 0 ] && say "--force: proceeding over ${#LIVE[@]} live run(s)"

# --- kill ---------------------------------------------------------------------
KILL=("${SERVICE_PIDS[@]:-}" "${WRAPPER_PIDS[@]:-}")
KILL=($(printf '%s\n' "${KILL[@]:-}" | grep -E '^[0-9]+$' | sort -un))

if [ "${#KILL[@]}" -eq 0 ]; then
  say "no harness services running"
else
  for p in "${KILL[@]}"; do say "kill $p  $(cmd_of "$p")"; done
  run kill "${KILL[@]}" 2>/dev/null
  if [ "$DRY" != 1 ]; then
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      still=0; for p in "${KILL[@]}"; do kill -0 "$p" 2>/dev/null && still=1; done
      [ "$still" = 0 ] && break
      sleep 0.5
    done
    for p in "${KILL[@]}"; do
      kill -0 "$p" 2>/dev/null && { say "SIGKILL $p (ignored SIGTERM)"; kill -9 "$p" 2>/dev/null; }
    done
  fi
fi

busy="$(lsof -nP $(printf -- '-iTCP:%s ' "${PORTS[@]}") -sTCP:LISTEN 2>/dev/null | tail -n +2)"
if [ -n "$busy" ]; then say "WARNING: ports still bound:"; echo "$busy"; else say "ports free: ${PORTS[*]}"; fi

# --- docker -------------------------------------------------------------------
if ! docker info >/dev/null 2>&1; then
  say "docker not reachable; skipping container/volume sweep"
  exit 0
fi

before="$(docker system df --format '{{.Type}} {{.Reclaimable}}' 2>/dev/null)"

if [ "$ALL" = 1 ]; then
  say "--all: pruning every stopped container and unused volume on this machine"
  run docker container prune -f
  run docker volume prune -f
else
  # Harbor names its compose project "<trial>__env", so containers land as
  # "<trial>__env-<service>-1" and volumes as "<trial>__env_<name>". Scoping to
  # that infix leaves unrelated Docker projects on this machine alone.
  CTRS=()
  while read -r c; do [ -n "$c" ] && CTRS+=("$c"); done < <(docker ps -aq \
      --filter status=exited --filter status=created --filter status=dead \
      --filter name='__env-' 2>/dev/null)
  if [ "${#CTRS[@]}" -gt 0 ]; then
    for c in "${CTRS[@]}"; do say "rm container $c  $(docker inspect -f '{{.Name}} {{.State.Status}}' "$c" 2>/dev/null)"; done
    run docker rm "${CTRS[@]}"
  else
    say "no stopped harness containers"
  fi

  # Volumes only AFTER containers: a volume still attached to a `Created`
  # container reads as in-use and would survive the sweep.
  VOLS=()
  while read -r v; do [ -n "$v" ] && VOLS+=("$v"); done < <(docker volume ls -q \
      --filter dangling=true --filter name='__env_' 2>/dev/null)
  if [ "${#VOLS[@]}" -gt 0 ]; then
    for v in "${VOLS[@]}"; do say "rm volume $v"; done
    run docker volume rm "${VOLS[@]}"
  else
    say "no unused harness volumes"
  fi
fi

say "images and build cache left intact (warm cache for the next run)"
[ "$DRY" != 1 ] && { echo; docker system df; }
exit 0
