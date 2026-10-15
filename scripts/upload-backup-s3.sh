#!/usr/bin/env bash
# Optional encrypted off-server backup. Requires AWS CLI, an existing
# private S3 bucket and a narrowly-scoped IAM role.
set -Eeuo pipefail
umask 077
BACKUP_DIR="${HOME}/pharmacare-backups"
: "${PHARMACARE_BACKUP_S3_BUCKET:?Set PHARMACARE_BACKUP_S3_BUCKET}"
command -v aws >/dev/null || { echo "Install AWS CLI first"; exit 1; }
latest="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'pharmacare-*.dump' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)"
test -n "$latest" && test -s "$latest" || { echo "No usable backup found"; exit 1; }
echo "Uploading encrypted copy of $(basename "$latest")"
aws s3 cp --only-show-errors --sse AES256 "$latest" \
 "s3://${PHARMACARE_BACKUP_S3_BUCKET}/pharmacare/$(basename "$latest")"
echo "Upload completed; remote retention and isolated restore validation remain necessary."
