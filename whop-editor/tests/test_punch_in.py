import subprocess
from pathlib import Path
import pytest

from config import settings
from editing.punch_in import render_punch_in, PunchInRenderError
from qc.video_check import verify_rendered_video, QCValidationError
from ingest.video import inspect_video_media


@pytest.fixture(scope="module")
def synthetic_test_video(tmp_path_factory):
    """Generates a tiny 2.5s vertical video (720x1280) with audio tone for testing."""
    temp_dir = tmp_path_factory.mktemp("video_test")
    test_file = temp_dir / "synthetic_test.mp4"

    cmd = [
        settings.FFMPEG_EXE,
        "-y",
        "-f", "lavfi",
        "-i", "testsrc=duration=2.5:size=720x1280:rate=30",
        "-f", "lavfi",
        "-i", "sine=frequency=440:duration=2.5",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(test_file)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return test_file


def test_punch_in_rendering_success(synthetic_test_video, tmp_path):
    out_file = tmp_path / "rendered_punchin.mp4"
    in_info = inspect_video_media(synthetic_test_video)

    result_path = render_punch_in(
        input_path=synthetic_test_video,
        start_time=0.8,
        end_time=1.8,
        scale=1.15,
        output_path=out_file
    )

    assert result_path.exists()
    assert result_path.stat().st_size > 0

    # Run QC
    qc = verify_rendered_video(result_path, expected_input_info=in_info)
    assert qc.passed is True
    assert qc.has_audio is True
    assert abs(qc.output_duration - in_info["duration"]) < 0.25


def test_punch_in_rejects_overwriting_source(synthetic_test_video):
    with pytest.raises(PunchInRenderError) as exc:
        render_punch_in(
            input_path=synthetic_test_video,
            start_time=0.5,
            end_time=1.5,
            scale=1.15,
            output_path=synthetic_test_video # Identical path
        )
    assert "must be distinct" in str(exc.value)


def test_punch_in_rejects_invalid_scale(synthetic_test_video, tmp_path):
    out_file = tmp_path / "bad_scale.mp4"
    with pytest.raises(PunchInRenderError) as exc:
        render_punch_in(
            input_path=synthetic_test_video,
            start_time=0.5,
            end_time=1.5,
            scale=1.0, # Must be > 1.0
            output_path=out_file
        )
    assert "Scale must be greater than 1.0" in str(exc.value)


def test_punch_in_rejects_invalid_window(synthetic_test_video, tmp_path):
    out_file = tmp_path / "bad_window.mp4"
    with pytest.raises(PunchInRenderError) as exc:
        render_punch_in(
            input_path=synthetic_test_video,
            start_time=2.0,
            end_time=1.0, # end < start
            scale=1.15,
            output_path=out_file
        )
    assert "must be strictly greater" in str(exc.value)


def test_punch_in_rendering_with_y_offset(synthetic_test_video, tmp_path):
    out_file = tmp_path / "rendered_y_offset.mp4"
    in_info = inspect_video_media(synthetic_test_video)

    result_path = render_punch_in(
        input_path=synthetic_test_video,
        start_time=0.5,
        end_time=1.5,
        scale=1.20,
        output_path=out_file,
        y_offset=100.0
    )

    assert result_path.exists()
    assert result_path.stat().st_size > 0

    qc = verify_rendered_video(result_path, expected_input_info=in_info)
    assert qc.passed is True
    assert qc.has_audio is True

