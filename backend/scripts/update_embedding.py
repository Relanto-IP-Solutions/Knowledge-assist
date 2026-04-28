"""One-off script: re-embed a manually updated answer_text row."""
from src.services.rag_engine.retrieval.embedding import embed_texts
from src.services.database_manager.connection import get_db_connection

OPPORTUNITY_ID = "oid10035"
QUESTION_ID = "QID-012"
TEXT = "Quarterly"

vec = embed_texts([TEXT])[0]
pgvec = "[" + ",".join(map(str, vec)) + "]"

con = get_db_connection()
cur = con.cursor()
cur.execute(
    """
    UPDATE answers
    SET answer_embedding = %s
    WHERE opportunity_id = %s
      AND question_id = %s
      AND answer_text = %s
    """,
    (pgvec, OPPORTUNITY_ID, QUESTION_ID, TEXT),
)
con.commit()
print(f"Updated {cur.rowcount} row(s)")
con.close()
