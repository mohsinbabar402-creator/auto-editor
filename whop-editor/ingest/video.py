import os
import subprocess
import uuid
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from config import settings
from db.repository import DatabaseRepository, RepositoryError

logger = logging.getLogger("whop_editor.ingest")

VALID_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


class IngestError(Exception):
    """Raised when video ingestion or validation fails."""
    pass


def inspect_video_media(file_path: Path) -> Dict[str, Any]:
    """
    Deterministically inspects video properties using FFmpeg/FFprobe or OpenCV fallback.
    Returns duration (seconds), width, height, has_audio, and fps.
    """
    if not file_path.exists():
        raise IngestError(f"Video file does not exist: {file_path}")
    if file_path.stat().st_size == 0:
        raise IngestError(f"Video file is empty (0 bytes): {file_path}")
    if file_path.suffix.lower() not in VALID_EXTENSIONS:
        raise IngestError(f"Unsupported video extension: {file_path.suffix}")

    # Use FFmpeg to inspect streams without full decode
    cmd = [
        settings.FFMPEG_EXE,
        "-i", str(file_path),
        "-hide_banner"
    ]
    try:
        proc = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, errors="replace")
        stderr = proc.stderr
    except FileNotFoundError:
        raise IngestError(f"FFmpeg binary not found at '{settings.FFMPEG_EXE}'.")
    except Exception as e:
        raise IngestError(f"Failed to execute FFmpeg inspection: {e}")

    # Parse stderr for Duration, Video stream, and Audio stream
    has_video = "Video:" in stderr
    has_audio = "Audio:" in stderr
    if not has_video:
        raise IngestError(f"No video stream found in {file_path.name}")

    duration = None
    width = None
    height = None
    fps = None

    for line in stderr.splitlines():
        line_clean = line.strip()
        if "Duration:" in line_clean and duration is None:
            # Duration: 00:00:10.50, start: ...
            parts = line_clean.split("Duration:")[1].split(",")[0].strip()
            try:
                h, m, s = parts.split(":")
                duration = float(h) * 3600 + float(m) * 60 + float(s)
            except Exception:
                pass
        if "Video:" in line_clean and (width is None or height is None):
            # Stream #0:0: Video: h264 ..., 1080x1920 ..., 30 fps
            parts = line_clean.split("Video:")[1].split(",")
            for p in parts:
                p = p.strip()
                if "x" in p:
                    dims = p.split(" ")[0].split("[")[0].strip()
                    if "x" in dims:
                        subparts = dims.split("x")
                        if len(subparts) == 2 and subparts[0].isdigit() and subparts[1].isdigit():
                            width = int(subparts[0])
                            height = int(subparts[1])
                if "fps" in p:
                    fps_str = p.split("fps")[0].strip()
                    try:
                        fps = float(fps_str)
                    except Exception:
                        pass

    if duration is None or duration <= 0:
        raise IngestError(f"Could not determine valid duration for {file_path.name}")

    return {
        "duration": duration,
        "width": width or 1080,
        "height": height or 1920,
        "fps": fps or 30.0,
        "has_audio": has_audio,
        "file_size": file_path.stat().st_size
    }


def register_input_video(
    file_path: str | Path,
    project_id: str,
    video_id: Optional[str] = None,
    repo: Optional[DatabaseRepository] = None
) -> Dict[str, Any]:
    """
    Validates video file and registers record in PostgreSQL repository.
    """
    path = Path(file_path).resolve()
    media_info = inspect_video_media(path)
    
    v_id = video_id or f"vid_{uuid.uuid4().hex[:12]}"
    active_repo = repo or DatabaseRepository()

    # Verify project exists
    proj = active_repo.get_project(project_id)
    if not proj:
        raise IngestError(f"Cannot register video: Project '{project_id}' does not exist.")

    registered = active_repo.register_video(
        video_id=v_id,
        project_id=project_id,
        file_path=str(path),
        status="registered"
    )

    active_repo.log_audit(
        audit_id=f"audit_ingest_{uuid.uuid4().hex[:8]}",
        action="REGISTER_VIDEO",
        target=v_id,
        detail=f"Registered video '{path.name}', duration={media_info['duration']:.2f}s"
    )

    registered.update(media_info)
    logger.info(f"Video registered: {v_id} ({path.name}, {media_info['duration']:.2f}s)")
    return registered
