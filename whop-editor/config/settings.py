import os
from pathlib import Path
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Data directories
DATA_DIR = BASE_DIR / "data"
INPUT_DIR = DATA_DIR / "input"
ANALYSIS_DIR = DATA_DIR / "analysis"
OUTPUT_DIR = DATA_DIR / "output"

INPUT_DIR.mkdir(parents=True, exist_ok=True)
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# PostgreSQL Configuration
DB_HOST = os.environ.get("PGHOST", os.environ.get("DB_HOST", "localhost"))
DB_PORT = int(os.environ.get("PGPORT", os.environ.get("DB_PORT", "5432")))
DB_NAME = os.environ.get("PGDATABASE", os.environ.get("DB_NAME", "whop_editor"))
DB_USER = os.environ.get("PGUSER", os.environ.get("DB_USER", "postgres"))
DB_PASSWORD = os.environ.get("PGPASSWORD", os.environ.get("DB_PASSWORD", "postgres"))

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# FFmpeg Executable Resolution
def resolve_ffmpeg_exe() -> str:
    env_ffmpeg = os.environ.get("FFMPEG_EXE")
    if env_ffmpeg and Path(env_ffmpeg).exists():
        return env_ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

FFMPEG_EXE = resolve_ffmpeg_exe()

# AI / Gemini Configuration
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-pro")

# Punch-In Editing Constraints & Timing Offsets
MIN_SCALE = 1.05
MAX_SCALE = 1.30
MIN_DURATION_MS = 200
MAX_DURATION_MS = 3000

# Configurable pre/post timing adjustment (ms) around word boundary
TIMING_PRE_OFFSET_MS = int(os.environ.get("TIMING_PRE_OFFSET_MS", "40"))
TIMING_POST_OFFSET_MS = int(os.environ.get("TIMING_POST_OFFSET_MS", "40"))

# Centralized Quality Gate & Emergency Iteration Limits
QUALITY_GATE_SCORE = float(os.environ.get("QUALITY_GATE_SCORE", "10.0"))
MAX_AUTO_ITERATIONS = int(os.environ.get("MAX_AUTO_ITERATIONS", "20"))

