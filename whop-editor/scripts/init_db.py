import logging
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.connection import transaction_scope, check_db_connection, DatabaseConnectionError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("init_db")


def init_database() -> bool:
    """Executes schema.sql against PostgreSQL and validates tables."""
    schema_path = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
    if not schema_path.exists():
        logger.error(f"Schema file not found at {schema_path}")
        return False

    if not check_db_connection():
        logger.error("PostgreSQL is not reachable. Check configuration.")
        return False

    sql = schema_path.read_text(encoding="utf-8")
    logger.info("Executing schema migrations...")

    try:
        with transaction_scope() as cur:
            cur.execute(sql)
            
            # Verify table creation
            expected_tables = [
                "projects", "videos", "knowledge", "evidence", "audit_log",
                "campaigns", "workers", "jobs", "reviews"
            ]
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = ANY(%s);
            """, (expected_tables,))
            found_tables = {row[0] for row in cur.fetchall()}
            
            missing = set(expected_tables) - found_tables
            if missing:
                logger.error(f"Missing tables after initialization: {missing}")
                return False
                
            logger.info(f"Database initialized successfully. Verified tables: {sorted(list(found_tables))}")
            return True
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False


if __name__ == "__main__":
    success = init_database()
    sys.exit(0 if success else 1)
