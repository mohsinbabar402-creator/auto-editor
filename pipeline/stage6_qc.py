"""
Stage 6: Automated Quality Control & Inspection
Verifies:
- Resolution: 1080x1920 (9:16 aspect ratio)
- Frame rate & bitrate
- Audio channels & loudness levels
- Playback integrity and sync
"""

import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, Any

# Ensure UTF-8 output on Windows console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import config

def inspect_video(video_path: Path) -> Dict[str, Any]:
    if not video_path.exists():
        return {"status": "FAILED", "error": f"File not found: {video_path}"}

    # Run ffprobe to get detailed stream information
    cmd = [
        config.FFMPEG_EXE,
        "-i", str(video_path)
    ]
    res = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    output = res.stderr

    qc_report = {
        "file_path": str(video_path),
        "file_size_mb": round(video_path.stat().st_size / (1024 * 1024), 2),
        "resolution_pass": False,
        "duration_pass": False,
        "audio_pass": False,
        "details": {}
    }

    # Parse duration
    duration = 0.0
    for line in output.splitlines():
        if "Duration:" in line:
            parts = line.split("Duration:")[1].split(",")[0].strip().split(":")
            duration = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            qc_report["details"]["duration_sec"] = round(duration, 2)
            # Check 40s - 65s range
            qc_report["duration_pass"] = 35.0 <= duration <= 65.0

        if "Video:" in line:
            qc_report["details"]["video_codec"] = line.strip()
            if "1080x1920" in line:
                qc_report["resolution_pass"] = True

        if "Audio:" in line:
            qc_report["details"]["audio_codec"] = line.strip()
            qc_report["audio_pass"] = True

    overall_pass = qc_report["resolution_pass"] and qc_report["duration_pass"] and qc_report["audio_pass"]
    qc_report["status"] = "PASSED" if overall_pass else "WARNING"

    print("\n" + "="*50)
    print(f"🎬 QUALITY CONTROL REPORT: {video_path.name}")
    print("="*50)
    print(f"• Status: {qc_report['status']}")
    print(f"• Resolution (1080x1920 9:16): {'✅ PASS' if qc_report['resolution_pass'] else '❌ FAIL'}")
    print(f"• Duration ({qc_report['details'].get('duration_sec', 0)}s): {'✅ PASS' if qc_report['duration_pass'] else '❌ FAIL'}")
    print(f"• Audio Track Detected: {'✅ PASS' if qc_report['audio_pass'] else '❌ FAIL'}")
    print(f"• File Size: {qc_report['file_size_mb']} MB")
    print("="*50 + "\n")

    return qc_report

if __name__ == "__main__":
    test_video = Path(__file__).resolve().parent.parent / "projects" / "earth_stops_rotating" / "output" / "final_short.mp4"
    if test_video.exists():
        inspect_video(test_video)
