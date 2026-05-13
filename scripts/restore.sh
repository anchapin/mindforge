#!/bin/bash
# scripts/restore.sh — run to restore from backup
# Usage: ./restore.sh <BACKUP_DIR>

set -euo pipefail

BACKUP_DIR="$1"                         # pass backup timestamp as argument
CONTAINER="mindforge-backend-1"

if [[ ! -d "$BACKUP_DIR" ]]; then
    echo "Backup directory not found: $BACKUP_DIR"
    exit 1
fi

# Stop services
docker compose stop

# Restore files
docker cp "$BACKUP_DIR/mindforge.db" "$CONTAINER:/app/data/mindforge.db"
docker cp "$BACKUP_DIR/chroma_data/." "$CONTAINER:/app/data/chroma/"

# Restart services
docker compose start

echo "Restore complete from $BACKUP_DIR"
