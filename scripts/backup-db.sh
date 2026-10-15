#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

cd "$HOME/cloudlaunch"

BACKUP_DIR="$HOME/pharmacare-backups"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

FILE="$BACKUP_DIR/pharmacare-$(date +%Y%m%d-%H%M%S).dump"
TEMP="${FILE}.partial"

trap 'rm -f "$TEMP"' EXIT

echo "Creating PostgreSQL backup..."

sudo docker compose exec -T db sh -c \
  'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "$TEMP"

test -s "$TEMP"

sudo docker compose exec -T db sh -c \
  'exec pg_restore -l >/dev/null' < "$TEMP"

mv "$TEMP" "$FILE"
trap - EXIT

echo "SUCCESS: Backup created and verified."
echo "Location: $FILE"
ls -lh "$FILE"
