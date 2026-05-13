#!/bin/bash
# scripts/backup.sh — run nightly via cron: 0 3 * * * /app/scripts/backup.sh
# Usage: ./backup.sh

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DEST="$BACKUP_DIR/$TIMESTAMP"
CONTAINER="mindforge-backend-1"        # docker compose container name

mkdir -p "$DEST"

# PGLite (SQLite)
docker cp "$CONTAINER:/app/data/mindforge.db" "$DEST/mindforge.db"

# ChromaDB
docker cp "$CONTAINER:/app/data/chroma" "$DEST/chroma_data/"

# Skill YAML files
docker cp "$CONTAINER:/app/backend/skills" "$DEST/skills/"

# Fernet key (critical — without it backups are useless)
# The key is stored in .env; back it up separately from the DB
cp .env "$DEST/.env.encrypted"          # .env itself should be encrypted at rest

# Retention: keep 7 days
find "$BACKUP_DIR" -maxdepth 1 -type d -mtime +7 -exec rm -rf {} \;

echo "Backup complete: $DEST"
