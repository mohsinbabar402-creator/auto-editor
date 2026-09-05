import logging
import subprocess
from pathlib import Path
from typing import Union

from config import settings

logger = logging.getLogger("whop_editor.editing.punch_in")


class PunchInRenderError(Exception):
    """Raised when the punch-in FFmpeg render fails."""
    pass


def render_punch_in(
    input_path: Union[str, Path],
    start_time: float,
    end_time: float,
    scale: float,
    output_path: Union[str, Path],
    y_offset: float = 0.0
) -> Path:
    """
    Renders a punch-in zoom onto input_path between start_time and end_time.
    Supports optional y_offset (in pixels) to shift the crop window vertically,
    preserving lower-third graphics/safe margins (y_offset > 0) or headroom (y_offset < 0).

    Contract:
    - Never overwrites source.
    - Preserves all audio channels.
    - Produces a valid, standards-compliant video file.
    - Safely computes crop and scale relative to input dimensions (iw, ih).
    - Uses safe subprocess argument lists (no shell execution).
    - Verifies output existence and non-zero byte size.
    """
    in_file = Path(input_path).resolve()
    out_file = Path(output_path).resolve()

    if not in_file.exists():
        raise PunchInRenderError(f"Input video does not exist: {in_file}")
    if in_file == out_file:
        raise PunchInRenderError(f"Output path must be distinct from input path. Input: {in_file}")
    if scale <= 1.0:
        raise PunchInRenderError(f"Scale must be greater than 1.0 for a punch-in. Provided: {scale}")
    if end_time <= start_time:
        raise PunchInRenderError(
            f"end_time ({end_time}s) must be strictly greater than start_time ({start_time}s)."
        )

    out_file.parent.mkdir(parents=True, exist_ok=True)

    # Format numbers safely
    s_val = round(scale, 3)
    t_start = round(start_time, 3)
    t_end = round(end_time, 3)
    y_off = round(y_offset, 2)

    # Vertical framing calculation:
    # Default centered: y=(ih-oh)/2
    # With y_offset: min(ih-oh, max(0, (ih-oh)/2 + y_off))
    if y_off == 0.0:
        y_calc = "(ih-oh)/2"
    else:
        y_calc = f"min(ih-oh\\,max(0\\,(ih-oh)/2+{y_off}))"

    # Dynamic zoom using overlay:
    # 1. Base video split into two streams [v_base] and [v_zoom_in]
    # 2. [v_zoom_in] is cropped to (iw/scale, ih/scale) with vertical framing offset
    # 3. Then scaled back to (iw, ih) of original
    # 4. Overlaid on [v_base] only between t_start and t_end
    filter_complex = (
        f"[0:v]split=2[v_base][v_zoom];"
        f"[v_zoom]crop=w=iw/{s_val}:h=ih/{s_val}:x=(iw-ow)/2:y={y_calc},"
        f"scale=iw*{s_val}:ih*{s_val}:flags=bicubic[zoomed];"
        f"[v_base][zoomed]overlay=x=0:y=0:enable='between(t,{t_start},{t_end})'[v_out]"
    )

    cmd = [
        settings.FFMPEG_EXE,
        "-y",
        "-i", str(in_file),
        "-filter_complex", filter_complex,
        "-map", "[v_out]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        str(out_file)
    ]

    logger.info(f"Executing FFmpeg punch-in: scale={s_val}x, window=[{t_start}s, {t_end}s]")
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace"
        )
        if proc.returncode != 0:
            logger.error(f"FFmpeg render failure. Stderr:\n{proc.stderr}")
            raise PunchInRenderError(f"FFmpeg process exited with code {proc.returncode}: {proc.stderr[:400]}")
    except FileNotFoundError:
        raise PunchInRenderError(f"FFmpeg binary not found at '{settings.FFMPEG_EXE}'.")
    except Exception as e:
        raise PunchInRenderError(f"Subprocess execution error during render: {e}") from e

    if not out_file.exists() or out_file.stat().st_size == 0:
        raise PunchInRenderError(f"Rendered output file was not created or is 0 bytes: {out_file}")

    logger.info(f"Render succeeded: {out_file.name} ({out_file.stat().st_size} bytes)")
    return out_file
