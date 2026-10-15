#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

cd "$HOME/cloudlaunch"

BACKUP_DIR="$HOME/pharmacare-backups"
BACKUP="${1:-}"

if [[ -z "$BACKUP" || ! -f "$BACKUP" ]]; then
  echo "Usage: scripts/restore-db.sh /full/path/to/backup.dump"
  exit 1
fi

BACKUP="$(realpath "$BACKUP")"

case "$BACKUP" in
  "$BACKUP_DIR"/*.dump) ;;
  *)
    echo "ERROR: Backup must be inside $BACKUP_DIR"
    exit 1
    ;;
esac

echo "Checking backup archive..."

sudo docker compose -p cloudlaunch exec -T db sh -c \
  'exec pg_restore -l >/dev/null' < "$BACKUP"

echo
echo "WARNING: Restoring will REPLACE current PharmaCare database records."
echo "This can remove sales, inventory changes, customers and other records"
echo "created after the selected backup."
echo

read -r -p "Type RESTORE to continue: " ANSWER

if [[ "$ANSWER" != "RESTORE" ]]; then
  echo "Cancelled. No database changes made."
  exit 1
fi

echo "Creating a pre-restore safety backup..."
bash scripts/backup-db.sh

echo "Stopping application during restore..."
sudo docker compose -p cloudlaunch stop app

echo "Restoring PostgreSQL database..."

if sudo docker compose -p cloudlaunch exec -T db sh -c \
  'exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --clean --if-exists --no-owner --no-privileges --single-transaction --exit-on-error' \
  < "$BACKUP"; then
  echo "Database restore completed."
else
  echo "RESTORE FAILED. Application remains stopped."
  echo "Investigate before restarting. Pre-restore backup is available."
  exit 1
fi

echo "Starting application..."
sudo docker compose -p cloudlaunch start app

echo "SUCCESS: Restore completed."
echo "Check application health before resuming use."
