"""Quick check of ingested data in pgvector for an opportunity."""

import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv


load_dotenv(_PROJECT_ROOT / "configs" / ".env", override=False)
load_dotenv(_PROJECT_ROOT / "configs" / "secrets" / ".env", override=True)

from src.services.database_manager.connection import get_db_connection


OPP_ID = "oid99"

con = get_db_connection()
cur = con.cursor()

# Check document_registry
cur.execute(
    """
    SELECT document_id, opportunity_id, total_chunks, updated_at
    FROM document_registry
    WHERE opportunity_id = %s
    ORDER BY updated_at DESC
    """,
    (OPP_ID,),
)
print(f"=== document_registry for {OPP_ID} ===")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[2]} chunks")

# Check chunk_registry with embeddings
cur.execute(
    """
    SELECT document_id, COUNT(*) as chunk_count,
           COUNT(embedding) as with_embedding
    FROM chunk_registry
    WHERE opportunity_id = %s
    GROUP BY document_id
    """,
    (OPP_ID,),
)
print()
print("=== chunk_registry summary ===")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]} chunks, {row[2]} with embeddings")

con.close()
