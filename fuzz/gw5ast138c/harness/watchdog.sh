#!/bin/bash
# Out-of-process stall watchdog for one harness batch (`P0.T22`).
#
# BINDING (fine-line CLAUDE.md "Long-running work", `spec-harness.md` §8): a
# watcher that lives inside the process it watches dies with it.  This script
# runs OUTSIDE the batch, judges liveness ONLY from artifact evidence (the
# batch pid and log-file mtimes -- never from anything the batch says about
# itself), and fires on stall, death AND completion.
#
# It ships here, beside the harness it guards, and NOT in $PIPE/tools
# (cross-phase F30), because it travels with the fork branch.
#
# Arming order: the watchdog is started BEFORE the batch.  It therefore takes a
# *pidfile* rather than a pid, writes WATCHDOG_ARMED immediately, and then waits
# for the batch to publish its pid.  A pid that never appears is a death.
#
# Usage:
#   watchdog.sh <batch_id> <batch_log> <watchdog_log> <pidfile> \
#               [stall_minutes] [poll_seconds] [arm_timeout_seconds]
#
# Log vocabulary (greppable, `spec-harness.md` §8):
#   WATCHDOG_ARMED    batch=<id> stall=<n>min poll=<n>s
#   WATCHDOG_STALL    batch=<id> newest=<file> age=<n>min
#   WATCHDOG_DEAD     batch=<id> exited WITHOUT BATCH_COMPLETE
#   WATCHDOG_COMPLETE batch=<id> saw BATCH_COMPLETE (clean exit)
# Exactly one ARMED line and exactly one terminal line (DEAD or COMPLETE) per run.
set -u

BATCH_ID=$1
BATCH_LOG=$2
WD_LOG=$3
PIDFILE=$4
STALL_MIN=${5:-90}
POLL=${6:-300}
ARM_TIMEOUT=${7:-300}

# The completion marker is the ONLY clean-exit verdict: the presence of this
# line in the batch log, not the process having exited.
MARKER="BATCH_COMPLETE ${BATCH_ID}"

# Liveness/completion are checked on a fine tick so a death is not hidden for a
# whole stall poll; the STALL check itself still runs at the spec'd `poll`
# cadence (`stall = D/10` floored 5 min capped 90 min, `poll = min(300s,
# stall/3)`), which is what the interval formula governs.
TICK=2
[ "$POLL" -lt "$TICK" ] && TICK=$POLL

LOG_DIR=$(dirname "$BATCH_LOG")
mkdir -p "$(dirname "$WD_LOG")"

sig() { echo "$(date +%H:%M:%S) $1" >> "$WD_LOG"; }

marker_seen() { [ -f "$BATCH_LOG" ] && grep -q "^${MARKER} " "$BATCH_LOG"; }

finish() {
  if marker_seen; then
    sig "WATCHDOG_COMPLETE batch=${BATCH_ID} saw BATCH_COMPLETE (clean exit)"
  else
    sig "WATCHDOG_DEAD batch=${BATCH_ID} exited WITHOUT BATCH_COMPLETE${1:+ ($1)} — resume with the identical batch command (run ids with a terminal row are skipped)"
  fi
  exit 0
}

sig "WATCHDOG_ARMED batch=${BATCH_ID} stall=${STALL_MIN}min poll=${POLL}s (independent process)"

# --- wait for the batch to publish its pid -------------------------------
BPID=""
WAITED=0
while [ -z "$BPID" ]; do
  if [ -s "$PIDFILE" ]; then
    BPID=$(head -1 "$PIDFILE" | tr -dc '0-9')
  fi
  [ -n "$BPID" ] && break
  marker_seen && finish
  if [ "$WAITED" -ge "$ARM_TIMEOUT" ]; then
    finish "batch pid never appeared in ${PIDFILE} after ${ARM_TIMEOUT}s"
  fi
  sleep "$TICK"
  WAITED=$(( WAITED + TICK ))
done

# --- watch ----------------------------------------------------------------
SINCE_STALL_CHECK=0
WARNED=""
while true; do
  sleep "$TICK"
  SINCE_STALL_CHECK=$(( SINCE_STALL_CHECK + TICK ))

  marker_seen && finish
  if ! kill -0 "$BPID" 2>/dev/null; then
    # Give a just-exited batch a moment to have its last write land.
    sleep 1
    finish "batch pid ${BPID} exited"
  fi

  [ "$SINCE_STALL_CHECK" -lt "$POLL" ] && continue
  SINCE_STALL_CHECK=0

  NEW=$(ls -t "$LOG_DIR"/"${BATCH_ID}"*.log 2>/dev/null | head -1)
  [ -n "$NEW" ] || continue
  AGE=$(( $(date +%s) - $(stat -f %m "$NEW") ))
  if [ "$AGE" -gt $(( STALL_MIN * 60 )) ]; then
    KEY="$NEW-$(( AGE / 3600 ))"
    if [ "$WARNED" != "$KEY" ]; then
      sig "WATCHDOG_STALL batch=${BATCH_ID} newest=$(basename "$NEW") age=$(( AGE / 60 ))min > ${STALL_MIN}min — batch pid ${BPID} ALIVE but producing nothing"
      WARNED="$KEY"
    fi
  fi
done
