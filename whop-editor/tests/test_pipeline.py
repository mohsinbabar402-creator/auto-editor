import subprocess
from pathlib import Path
import pytest

from config import settings
from pipeline.run import run_stage1_pipeline, PipelineResult
from ai.editor import AIEditor
from db.connection import check_db_connection
from db.repository import DatabaseRepository


class MockAIEditor(AIEditor):
    """Deterministic AI Editor for test runs."""
    def propose_punch_in(self, transcript, project_niche="", **kwargs):
        # Predictably select the second word with 1.15 scale
        target_idx = 1 if len(transcript) > 1 else 0
        return {
            "word_index": target_idx,
            "scale": 1.15,
            "duration_ms": 700
        }


class MockDatabaseRepository:
    """Mock repository for running pipeline tests without live PostgreSQL."""
    def __init__(self):
        self.projects = {"proj_whop_shortform": {"id": "proj_whop_shortform", "name": "Whop", "niche_description": "Edu"}}
        self.videos = {}
        self.knowledge = {}
        self.evidence = {}
        self.audit = {}

    def get_project(self, project_id):
        return self.projects.get(project_id)

    def create_project(self, project_id, name, niche_description):
        self.projects[project_id] = {"id": project_id, "name": name, "niche_description": niche_description}
        return self.projects[project_id]

    def register_video(self, video_id, project_id, file_path, status="registered"):
        self.videos[video_id] = {"id": video_id, "project_id": project_id, "file_path": file_path, "status": status}
        return self.videos[video_id]

    def update_video_status(self, video_id, status):
        if video_id in self.videos:
            self.videos[video_id]["status"] = status

    def get_video(self, video_id):
        return self.videos.get(video_id)

    def create_knowledge_candidate(self, knowledge_id, project_id, event_type, action_type, parameters_json, confidence=0.3, sample_size=0):
        self.knowledge[knowledge_id] = {
            "id": knowledge_id, "project_id": project_id, "event_type": event_type,
            "action_type": action_type, "parameters_json": parameters_json, "confidence": confidence
        }
        return self.knowledge[knowledge_id]

    def record_evidence(self, evidence_id, knowledge_id, video_id, outcome_note, metric_value=None):
        self.evidence[evidence_id] = {"id": evidence_id, "knowledge_id": knowledge_id, "outcome_note": outcome_note}
        return self.evidence[evidence_id]

    def log_audit(self, audit_id, action, target, detail):
        self.audit[audit_id] = {"id": audit_id, "action": action, "target": target, "detail": detail}
        return self.audit[audit_id]


@pytest.fixture(scope="module")
def sample_test_clip(tmp_path_factory):
    """Creates a 3-second vertical clip for pipeline testing."""
    temp_dir = tmp_path_factory.mktemp("pipeline_clip")
    clip = temp_dir / "sample_talking_head.mp4"
    cmd = [
        settings.FFMPEG_EXE,
        "-y",
        "-f", "lavfi",
        "-i", "testsrc=duration=3.0:size=720x1280:rate=30",
        "-f", "lavfi",
        "-i", "sine=frequency=1000:duration=3.0",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(clip)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return clip


def test_pipeline_execution_with_mock_components(sample_test_clip, monkeypatch):
    mock_repo = MockDatabaseRepository()
    mock_ai = MockAIEditor()

    # Mock whisper transcription output to avoid downloading Whisper weights in unit tests
    def mock_transcribe(video_path, video_id, model_size="tiny"):
        return {
            "video_id": video_id,
            "text": "Start scaling your community revenue today.",
            "words": [
                {"index": 0, "word": "Start", "start": 0.2, "end": 0.5},
                {"index": 1, "word": "scaling", "start": 0.6, "end": 1.1},
                {"index": 2, "word": "your", "start": 1.2, "end": 1.4},
                {"index": 3, "word": "community", "start": 1.5, "end": 2.0},
                {"index": 4, "word": "revenue", "start": 2.1, "end": 2.6},
                {"index": 5, "word": "today", "start": 2.7, "end": 2.9}
            ],
            "language": "en"
        }

    monkeypatch.setattr("pipeline.run.transcribe_video_words", mock_transcribe)

    result = run_stage1_pipeline(
        input_video_path=sample_test_clip,
        project_id="proj_whop_shortform",
        repo=mock_repo,
        ai_editor=mock_ai,
        output_filename="test_pipeline_output.mp4"
    )

    assert result.success is True
    assert result.selected_word == "scaling"
    assert result.selected_word_index == 1
    assert result.scale == 1.15
    assert result.output_path is not None
    assert Path(result.output_path).exists()
    assert Path(result.output_path).stat().st_size > 0

    # Verify repository state
    assert len(mock_repo.videos) >= 1
    assert len(mock_repo.knowledge) >= 1
    assert len(mock_repo.evidence) >= 1
    assert len(mock_repo.audit) >= 1
