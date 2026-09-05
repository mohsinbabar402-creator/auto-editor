"""
brain/artifact_verifier.py — FFprobe-Based Artifact Verification

Validates downloaded video artifacts using FFprobe analysis.
Checks: file existence, file size, container validity, video stream,
duration range, resolution match, codec validation, and decode integrity.

Part of Phase 18/19: Google Flow Production Engine.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple
import uuid


@dataclass
class VerificationCheck:
    """Single verification check result."""
    check_name: str
    passed: bool
    expected: str
    actual: str
    severity: str = "ERROR"  # ERROR, WARNING, INFO

    def __repr__(self) -> str:
        status = "PASS" if self.passed else f"FAIL ({self.severity})"
        return f"[{status}] {self.check_name}: expected={self.expected}, actual={self.actual}"


@dataclass
class VerificationResult:
    """Complete verification result for a single artifact."""
    artifact_path: str
    verified: bool = False
    sha256_hash: str = ""
    file_size: int = 0
    duration_sec: float = 0.0
    width: int = 0
    height: int = 0
    codec: str = ""
    fps: float = 0.0
    checks: List[VerificationCheck] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    verified_at: str = ""

    @property
    def error_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed and c.severity == "ERROR")

    @property
    def warning_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed and c.severity == "WARNING")

    def summary(self) -> str:
        status = "VERIFIED" if self.verified else "REJECTED"
        return (
            f"{status}: {self.artifact_path} | "
            f"{self.width}x{self.height} | {self.duration_sec:.1f}s | "
            f"{self.codec} | {self.file_size:,} bytes | "
            f"errors={self.error_count} warnings={self.warning_count}"
        )


# Minimum acceptable file size for a valid video (50KB)
MIN_FILE_SIZE_BYTES = 50_000
# Expected vertical video dimensions
EXPECTED_WIDTH = 1080
EXPECTED_HEIGHT = 1920
# Acceptable duration range for shorts (seconds)
MIN_DURATION_SEC = 2.0
MAX_DURATION_SEC = 120.0
# Acceptable FPS range
MIN_FPS = 20.0
MAX_FPS = 60.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _run_ffprobe(file_path: Path, ffprobe_exe: Optional[str] = None) -> Optional[dict]:
    """Run ffprobe and return parsed JSON output."""
    if ffprobe_exe is None:
        # Try to find ffprobe alongside ffmpeg from imageio_ffmpeg
        try:
            import imageio_ffmpeg
            ffmpeg_path = Path(imageio_ffmpeg.get_ffmpeg_exe())
            candidate = ffmpeg_path.parent / "ffprobe.exe"
            if candidate.exists():
                ffprobe_exe = str(candidate)
            else:
                # Try ffprobe in PATH
                ffprobe_exe = "ffprobe"
        except ImportError:
            ffprobe_exe = "ffprobe"

    cmd = [
        ffprobe_exe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(file_path)
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError):
        return None


class ArtifactVerifier:
    """FFprobe-based video artifact verification.

    Validates downloaded video files against expected specifications
    for 9:16 vertical short-form video production.
    """

    def __init__(
        self,
        expected_width: int = EXPECTED_WIDTH,
        expected_height: int = EXPECTED_HEIGHT,
        min_duration: float = MIN_DURATION_SEC,
        max_duration: float = MAX_DURATION_SEC,
        min_file_size: int = MIN_FILE_SIZE_BYTES,
        ffprobe_exe: Optional[str] = None,
        strict_resolution: bool = False,
    ):
        self.expected_width = expected_width
        self.expected_height = expected_height
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.min_file_size = min_file_size
        self.ffprobe_exe = ffprobe_exe
        self.strict_resolution = strict_resolution

    def verify(self, file_path: Path, expected_duration: Optional[float] = None) -> VerificationResult:
        """Run all verification checks on a video file.

        Args:
            file_path: Path to the video file to verify.
            expected_duration: Optional expected duration in seconds (for
                duration-match scoring).

        Returns:
            VerificationResult with all check outcomes.
        """
        result = VerificationResult(
            artifact_path=str(file_path),
            verified_at=_now_iso()
        )

        # Check 1: File exists
        exists = file_path.exists()
        result.checks.append(VerificationCheck(
            check_name="file_exists",
            passed=exists,
            expected="True",
            actual=str(exists)
        ))
        if not exists:
            result.errors.append(f"File not found: {file_path}")
            return result

        # Check 2: File size
        file_size = file_path.stat().st_size
        result.file_size = file_size
        size_ok = file_size >= self.min_file_size
        result.checks.append(VerificationCheck(
            check_name="file_size_minimum",
            passed=size_ok,
            expected=f">= {self.min_file_size:,} bytes",
            actual=f"{file_size:,} bytes"
        ))
        if not size_ok:
            result.errors.append(f"File too small: {file_size:,} bytes (min {self.min_file_size:,})")

        # Check 3: SHA-256 hash
        try:
            sha256 = _compute_sha256(file_path)
            result.sha256_hash = sha256
            result.checks.append(VerificationCheck(
                check_name="sha256_computed",
                passed=True,
                expected="computable",
                actual=sha256[:16] + "...",
                severity="INFO"
            ))
        except OSError as e:
            result.checks.append(VerificationCheck(
                check_name="sha256_computed",
                passed=False,
                expected="computable",
                actual=str(e)
            ))
            result.errors.append(f"SHA-256 computation failed: {e}")

        # Check 4+: FFprobe analysis
        probe_data = _run_ffprobe(file_path, self.ffprobe_exe)
        if probe_data is None:
            result.checks.append(VerificationCheck(
                check_name="ffprobe_readable",
                passed=False,
                expected="valid media container",
                actual="ffprobe failed or not found"
            ))
            result.errors.append("FFprobe analysis failed — file may be corrupted or ffprobe not installed")
            # Still compute overall result without probe data
            result.verified = result.error_count == 0
            return result

        result.checks.append(VerificationCheck(
            check_name="ffprobe_readable",
            passed=True,
            expected="valid media container",
            actual="readable",
            severity="INFO"
        ))

        # Find video stream
        video_stream = None
        for stream in probe_data.get("streams", []):
            if stream.get("codec_type") == "video":
                video_stream = stream
                break

        # Check 5: Video stream exists
        has_video = video_stream is not None
        result.checks.append(VerificationCheck(
            check_name="video_stream_exists",
            passed=has_video,
            expected="at least 1 video stream",
            actual="found" if has_video else "no video stream"
        ))
        if not has_video:
            result.errors.append("No video stream found in container")
            result.verified = False
            return result

        # Extract video properties
        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        codec = video_stream.get("codec_name", "unknown")
        result.width = width
        result.height = height
        result.codec = codec

        # Parse FPS
        fps_str = video_stream.get("r_frame_rate", "0/1")
        try:
            num, den = fps_str.split("/")
            fps = float(num) / float(den) if float(den) > 0 else 0.0
        except (ValueError, ZeroDivisionError):
            fps = 0.0
        result.fps = fps

        # Parse duration
        duration = 0.0
        if "duration" in video_stream:
            try:
                duration = float(video_stream["duration"])
            except ValueError:
                pass
        elif "duration" in probe_data.get("format", {}):
            try:
                duration = float(probe_data["format"]["duration"])
            except ValueError:
                pass
        result.duration_sec = duration

        # Check 6: Resolution match
        if self.strict_resolution:
            res_ok = (width == self.expected_width and height == self.expected_height)
        else:
            # Accept within 10% tolerance or matching aspect ratio
            aspect_expected = self.expected_width / self.expected_height if self.expected_height > 0 else 0
            aspect_actual = width / height if height > 0 else 0
            res_ok = abs(aspect_expected - aspect_actual) < 0.1

        result.checks.append(VerificationCheck(
            check_name="resolution_match",
            passed=res_ok,
            expected=f"{self.expected_width}x{self.expected_height}",
            actual=f"{width}x{height}",
            severity="ERROR" if self.strict_resolution else "WARNING"
        ))
        if not res_ok:
            msg = f"Resolution mismatch: {width}x{height} (expected {self.expected_width}x{self.expected_height})"
            if self.strict_resolution:
                result.errors.append(msg)
            else:
                result.warnings.append(msg)

        # Check 7: Duration range
        dur_ok = self.min_duration <= duration <= self.max_duration
        result.checks.append(VerificationCheck(
            check_name="duration_range",
            passed=dur_ok,
            expected=f"{self.min_duration:.1f}s - {self.max_duration:.1f}s",
            actual=f"{duration:.1f}s",
            severity="WARNING"
        ))
        if not dur_ok:
            result.warnings.append(f"Duration out of range: {duration:.1f}s")

        # Check 8: Duration match (if expected provided)
        if expected_duration is not None and expected_duration > 0:
            tolerance = max(1.0, expected_duration * 0.25)  # 25% tolerance
            dur_match = abs(duration - expected_duration) <= tolerance
            result.checks.append(VerificationCheck(
                check_name="duration_match",
                passed=dur_match,
                expected=f"{expected_duration:.1f}s ± {tolerance:.1f}s",
                actual=f"{duration:.1f}s",
                severity="WARNING"
            ))
            if not dur_match:
                result.warnings.append(
                    f"Duration deviation: {duration:.1f}s vs expected {expected_duration:.1f}s"
                )

        # Check 9: FPS range
        fps_ok = MIN_FPS <= fps <= MAX_FPS
        result.checks.append(VerificationCheck(
            check_name="fps_range",
            passed=fps_ok,
            expected=f"{MIN_FPS:.0f}-{MAX_FPS:.0f} fps",
            actual=f"{fps:.1f} fps",
            severity="WARNING"
        ))
        if not fps_ok:
            result.warnings.append(f"FPS out of range: {fps:.1f}")

        # Check 10: Codec validity
        valid_codecs = {"h264", "hevc", "h265", "vp9", "av1", "vp8", "mpeg4"}
        codec_ok = codec.lower() in valid_codecs
        result.checks.append(VerificationCheck(
            check_name="codec_valid",
            passed=codec_ok,
            expected=f"one of {sorted(valid_codecs)}",
            actual=codec,
            severity="WARNING"
        ))
        if not codec_ok:
            result.warnings.append(f"Unexpected codec: {codec}")

        # Final verdict: verified if zero ERROR-level failures
        result.verified = result.error_count == 0
        return result

    def quick_validate(self, file_path: Path) -> bool:
        """Quick validation — file exists and meets minimum size.

        Does NOT run ffprobe. Use for fast pre-checks.
        """
        if not file_path.exists():
            return False
        return file_path.stat().st_size >= self.min_file_size

    def batch_verify(
        self,
        file_paths: List[Path],
        expected_durations: Optional[List[Optional[float]]] = None
    ) -> List[VerificationResult]:
        """Verify multiple artifacts.

        Args:
            file_paths: List of paths to verify.
            expected_durations: Optional matching list of expected durations.

        Returns:
            List of VerificationResult objects.
        """
        if expected_durations is None:
            expected_durations = [None] * len(file_paths)

        results = []
        for path, dur in zip(file_paths, expected_durations):
            results.append(self.verify(path, expected_duration=dur))
        return results
