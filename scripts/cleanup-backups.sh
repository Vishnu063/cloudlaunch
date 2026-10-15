#!/usr/bin/env bash
set -euo pipefail

cd /home/ubuntu/pharmacare-backups

# Retain the 7 newest scheduled backups only.
find . -maxdepth 1 -type f -name 'pharmacare-*.dump' -printf '%T@ %p\n' |
  sort -nr |
  tail -n +8 |
  cut -d' ' -f2- |
  while IFS= read -r file; do
    rm -- "$file"
  done
