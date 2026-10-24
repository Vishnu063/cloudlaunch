#!/bin/sh
# Optional, best-effort producer. Never send secrets or raw build logs.
set -eu
status=${1:?Deployment status required}
case "$status" in started|succeeded|failed|rollback_started|rollback_succeeded|rollback_failed) ;; *) exit 2 ;; esac
[ -n "${OPS_PILOT_CLIENT:-}" ] || exit 0
[ -f "$OPS_PILOT_CLIENT" ] || { echo 'Configured event client is unavailable' >&2; exit 1; }
release="$(git rev-parse --verify HEAD)-${BUILD_NUMBER:-local}"
# Persist the exact timestamp so a Jenkins retry keeps an identical payload.
audit_dir=${CLOUDLAUNCH_EVENT_DIR:-.deployment-events}
mkdir -p "$audit_dir"
chmod 700 "$audit_dir"
stamp_file="$audit_dir/$release-$status.timestamp"
if [ ! -f "$stamp_file" ]; then
  (umask 077; date -u +%Y-%m-%dT%H:%M:%SZ > "$stamp_file")
fi
python3 "$OPS_PILOT_CLIENT" --service "${OPS_PILOT_SERVICE:-pharmacy-app}" \
  --release-id "$release" --status "$status" --event-id "$release:$status" \
  --correlation-id "$release" --timestamp "$(cat "$stamp_file")" \
  --audit-file "$audit_dir/events.jsonl"
