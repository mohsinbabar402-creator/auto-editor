import os
import subprocess
import sys
import time
import logging
from pathlib import Path

# Add whop-editor to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from db.connection import check_db_connection
from scripts.init_db import init_database
from scripts.seed_project import seed_default_project

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("start_postgres")

PG_DIR = Path(__file__).resolve().parent.parent / "tools" / "pgsql"
BIN_DIR = PG_DIR / "bin"
DATA_DIR = PG_DIR / "data"
LOG_FILE = PG_DIR / "server.log"


def setup_and_start_postgres() -> bool:
    """Sets up local portable PostgreSQL instance and starts it."""
    # Check if postgres is already reachable
    if check_db_connection():
        logger.info("PostgreSQL is already running and reachable!")
        init_database()
        seed_default_project()
        return True

    initdb_exe = BIN_DIR / "initdb.exe"
    pg_ctl_exe = BIN_DIR / "pg_ctl.exe"
    createdb_exe = BIN_DIR / "createdb.exe"

    if not (initdb_exe.exists() and pg_ctl_exe.exists()):
        logger.error(f"PostgreSQL binaries not found at {BIN_DIR}")
        return False

    # 1. Initialize data cluster if needed
    if not DATA_DIR.exists() or not (DATA_DIR / "PG_VERSION").exists():
        logger.info(f"Initializing new PostgreSQL data cluster at {DATA_DIR}...")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        init_cmd = [
            str(initdb_exe),
            "-D", str(DATA_DIR),
            "-U", settings.DB_USER,
            "-A", "trust",
            "-E", "UTF8"
        ]
        res = subprocess.run(init_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            logger.error(f"initdb failed: {res.stderr}")
            return False
        logger.info("Data cluster initialized successfully.")

    # 2. Start server
    logger.info("Starting PostgreSQL server...")
    start_cmd = [
        str(pg_ctl_exe),
        "-D", str(DATA_DIR),
        "-l", str(LOG_FILE),
        "-o", f"-p {settings.DB_PORT}",
        "start"
    ]
    res = subprocess.run(start_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0 and "already running" not in res.stderr:
        logger.error(f"pg_ctl start failed: {res.stderr}")

    # Wait for server to accept connections
    for _ in range(15):
        time.sleep(1)
        if check_db_connection():
            break

    # 3. Create database if it doesn't exist
    try:
        chk_conn = subprocess.run(
            [str(createdb_exe), "-U", settings.DB_USER, "-p", str(settings.DB_PORT), settings.DB_NAME],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        if chk_conn.returncode == 0:
            logger.info(f"Created database '{settings.DB_NAME}'.")
    except Exception as e:
        logger.info(f"Database creation notice: {e}")

    # 4. Initialize schema and seed project
    if check_db_connection():
        logger.info("PostgreSQL is verified reachable! Initializing schema...")
        init_database()
        seed_default_project()
        return True

    logger.error("Could not establish connection to PostgreSQL.")
    return False


if __name__ == "__main__":
    ok = setup_and_start_postgres()
    sys.exit(0 if ok else 1)
