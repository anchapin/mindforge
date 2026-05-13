#!/bin/bash
# scripts/delete_project.sh — permanently delete all data for a project
# Usage: ./delete_project.sh <PROJECT_ID> [--confirm]

set -euo pipefail
PROJECT_ID="${1:-}"
CONFIRM="${2:-}"

if [[ "$CONFIRM" != "--confirm" ]]; then
    echo "ERROR: Confirmation required."
    echo "Usage: ./delete_project.sh <PROJECT_ID> --confirm"
    echo ""
    echo "This will PERMANENTLY DELETE all data for project: $PROJECT_ID"
    echo "  - All task history from PGLite"
    echo "  - All semantic memories from ChromaDB"
    echo "  - All integration credentials"
    echo "  - All skill configurations"
    echo ""
    echo "This action CANNOT be undone."
    exit 1
fi

BACKUP_CONTAINER="mindforge-backend-1"

echo "DELETING project: $PROJECT_ID"
echo "  Deleting PGLite records..."
docker exec "$BACKUP_CONTAINER" python - << 'EOF'
import sqlite3, sys
project_id = sys.argv[1]
conn = sqlite3.connect("/app/data/mindforge.db")
for table in ["tasks", "integrations", "skills", "episodic_memory"]:
    conn.execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
conn.commit()
print(f"  PGLite records deleted from {len(conn.execute(f'SELECT 1 FROM tasks WHERE project_id = ?', (project_id,)).fetchall())} remaining tasks")
EOF

echo "  Deleting ChromaDB semantic memories..."
docker exec "$BACKUP_CONTAINER" python - << 'EOF'
import chromadb, sys
project_id = sys.argv[1]
client = chromadb.PersistentClient(path="/app/data/chroma")
collection = client.get_collection("memory")
ids_to_del = [m["id"] for m in collection.get(where={"project_id": project_id})["metadatas"] or [] if m.get("project_id") == project_id]
if ids_to_del:
    collection.delete(ids=ids_to_del)
    print(f"  Deleted {len(ids_to_del)} ChromaDB vectors")
else:
    print("  No ChromaDB vectors found for project")
EOF

echo ""
echo "Deletion complete for project: $PROJECT_ID"
echo "NOTE: Encrypted integration tokens in the Fernet key store are now orphaned."
echo "      They are cryptographically inaccessible but the ciphertext blobs remain."
