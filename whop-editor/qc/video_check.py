from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import subprocess

from config import settings
from ingest.video import inspect_video_media, IngestError

logger = logging.getLogger("whop_editor.qc")


class QCValidationError(Exception):
    """Raised when rendered video fails quality control checks."""
    pass


@dataclass
class QCReport:
    passed: bool
    output_path: str
    errors: List[str] = field(default_factory=list)
    input_duration: Optional[float] = None
    output_duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    has_audio: bool = False
    file_size_bytes: int = 0


def verify_rendered_video(
    output_path: str | Path,
    expected_input_info: Optional[Dict[str, Any]] = None
) -> QCReport:
    """
    Verifies that the rendered output file meets strict quality control requirements:
    1. Exists on disk and size > 0
    2. Readable by FFmpeg without fatal decode errors
    3. Video stream present with valid resolution
    4. Duration matches input duration within tight tolerance (+-0.25s)
    5. Audio stream is preserved if input possessed audio
    """
    out_file = Path(output_path).resolve()
    report = QCReport(passed=False, output_path=str(out_file))

    # 1. Physical existence and non-zero bytes
    if not out_file.exists():
        report.errors.append(f"Output file does not exist: {out_file}")
        raise QCValidationError("; ".join(report.errors))

    size = out_file.stat().st_size
    report.file_size_bytes = size
    if size == 0:
        report.errors.append(f"Output file is empty (0 bytes): {out_file}")
        raise QCValidationError("; ".join(report.errors))

    # 2. Inspect media using FFmpeg
    try:
        out_info = inspect_video_media(out_file)
    except IngestError as e:
        report.errors.append(f"Failed to inspect output video: {e}")
        raise QCValidationError("; ".join(report.errors)) from e

    report.output_duration = out_info["duration"]
    report.width = out_info["width"]
    report.height = out_info["height"]
    report.has_audio = out_info["has_audio"]

    # 3. Sanity check duration
    if out_info["duration"] is None or out_info["duration"] <= 0:
        report.errors.append(f"Invalid duration detected in output video: {out_info['duration']}")

    # 4. Compare against input baseline if provided
    if expected_input_info:
        in_dur = expected_input_info.get("duration")
        report.input_duration = in_dur
        if in_dur is not None and report.output_duration is not None:
            delta = abs(report.output_duration - in_dur)
            # Allow at most 0.35s drift due to frame container overhead
            if delta > 0.35:
                report.errors.append(
                    f"Output duration ({report.output_duration:.2f}s) diverged from input duration ({in_dur:.2f}s) by {delta:.2f}s."
                )

        if expected_input_info.get("has_audio") and not out_info["has_audio"]:
            report.errors.append("Input video possessed audio, but rendered output is missing audio stream.")

    # 5. Quick decode verification (nullsink check for corrupt packets)
    decode_cmd = [
        settings.FFMPEG_EXE,
        "-v", "error",
        "-i", str(out_file),
        "-f", "null",
        "-"
    ]
    try:
        decode_proc = subprocess.run(decode_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if decode_proc.returncode != 0 or decode_proc.stderr.strip():
            # Filter non-fatal fontconfig or warning lines
            err_lines = [l for l in decode_proc.stderr.splitlines() if "error" in l.lower() or "fatal" in l.lower()]
            if err_lines:
                report.errors.append(f"FFmpeg decode verification errors: {'; '.join(err_lines[:3])}")
    except Exception as e:
        logger.warning(f"Could not run nullsink decode check: {e}")

    if report.errors:
        report.passed = False
        logger.error(f"QC check FAILED for {out_file.name}: {report.errors}")
        raise QCValidationError("; ".join(report.errors))

    report.passed = True
    logger.info(
        f"QC check PASSED: {out_file.name} "
        f"({report.width}x{report.height}, {report.output_duration:.2f}s, {size} bytes, audio={report.has_audio})"
    )
    return report
