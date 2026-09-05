import psycopg2
from psycopg2 import pool, OperationalError, DatabaseError
from contextlib import contextmanager
from typing import Generator
import logging

from config import settings

logger = logging.getLogger("whop_editor.db")


class DatabaseConnectionError(Exception):
    """Raised when connecting to PostgreSQL fails."""
    pass


class DatabaseTransactionError(Exception):
    """Raised when a PostgreSQL transaction fails."""
    pass


def get_raw_connection():
    """Establishes and returns a direct PostgreSQL connection."""
    try:
        conn = psycopg2.connect(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            dbname=settings.DB_NAME,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            connect_timeout=5
        )
        return conn
    except OperationalError as e:
        logger.error(f"PostgreSQL connection failed to {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}: {e}")
        raise DatabaseConnectionError(f"Could not connect to PostgreSQL: {e}") from e
    except Exception as e:
        logger.error(f"Unexpected database error: {e}")
        raise DatabaseConnectionError(f"Database error: {e}") from e


def check_db_connection() -> bool:
    """Verifies that PostgreSQL is reachable."""
    try:
        conn = get_raw_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
        conn.close()
        return True
    except Exception as e:
        logger.warning(f"PostgreSQL connection check failed: {e}")
        return False


@contextmanager
def transaction_scope() -> Generator[psycopg2.extensions.cursor, None, None]:
    """
    Context manager providing transactional execution.
    Automatically commits on normal exit and rolls back on any exception.
    Ensures connection is always closed.
    """
    conn = get_raw_connection()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
            logger.info("Transaction rolled back successfully.")
        except Exception as rb_err:
            logger.error(f"Rollback failed: {rb_err}")
        raise DatabaseTransactionError(f"Transaction aborted: {e}") from e
    finally:
        try:
            conn.close()
        except Exception:
            pass
