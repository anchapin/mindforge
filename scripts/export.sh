#!/bin/bash
# scripts/export.sh — export all data for a project as JSON
# Usage: ./export.sh <PROJECT_ID> [output_dir]

set -euo pipefail
PROJECT_ID="${1:-default}"
OUTPUT_DIR="${2:-./exports}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
EXPORT_DIR="$OUTPUT_DIR/${PROJECT_ID}_${TIMESTAMP}"
mkdir -p "$EXPORT_DIR"

BACKUP_CONTAINER="mindforge-backend-1"
DB_PATH="/app/data/mindforge.db"
CHROMA_DATA="/app/data/chroma"

echo "Exporting project: $PROJECT_ID"

# 1. Export PGLite task history + integrations + skills
docker exec "$BACKUP_CONTAINER" python - << 'EOF'
import sqlite3, json, sys
project_id = sys.argv[1]
out_dir = sys.argv[2]
conn = sqlite3.connect(out_dir + "/_pglite_export.db")
conn.row_factory = sqlite3.Row
with open(out_dir + "/tasks.json", "w") as f:
    json.dump([dict(r) for r in conn.execute(
        "SELECT * FROM tasks WHERE project_id = ?", (project_id,)
    )], f, indent=2, default=str)
with open(out_dir + "/integrations.json", "w") as f:
    json.dump([dict(r) for r in conn.execute(
        "SELECT * FROM integrations WHERE project_id = ?", (project_id,)
    )], f, indent=2, default=str)
with open(out_dir + "/skills.json", "w") as f:
    json.dump([dict(r) for r in conn.execute(
        "SELECT * FROM skills WHERE project_id = ?", (project_id,)
    )], f, indent=2, default=str)
EOF

# 2. Export ChromaDB semantic memories (metadata includes project_id)
docker exec "$BACKUP_CONTAINER" python - << 'EOF'
import chromadb, json, sys
project_id = sys.argv[1]
out_dir = sys.argv[2]
client = chromadb.PersistentClient(path=out_dir + "/_chroma_export")
collection = client.get_collection("memory")
results = collection.get(where={"project_id": project_id})
with open(out_dir + "/semantic_memory.json", "w") as f:
    json.dump(results, f, indent=2, default=str)
EOF

# 3. Create manifest
cat > "$EXPORT_DIR/manifest.json" << 'EOF'
{
  "project_id": "%s",
  "exported_at": "%s",
  "files": ["tasks.json", "integrations.json", "skills.json", "semantic_memory.json"],
  "format": "MindForge local export v1"
}
EOF

echo "Export complete: $EXPORT_DIR"
echo "Total size: $(du -sh $EXPORT_DIR | cut -f1)"
