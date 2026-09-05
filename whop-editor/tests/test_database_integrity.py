import json
import pytest
import uuid

from db.connection import check_db_connection, transaction_scope, DatabaseConnectionError, DatabaseTransactionError
from db.repository import (
    DatabaseRepository,
    DuplicateEntityError,
    ForeignKeyMissingError,
    EntityNotFoundError,
    RepositoryError
)
from workers.models import WorkerStatus


@pytest.fixture
def repo():
    return DatabaseRepository()


@pytest.fixture
def test_project(repo):
    p_id = f"test_proj_{uuid.uuid4().hex[:8]}"
    repo.create_project(
        project_id=p_id,
        name="Integrity Audit Test Project",
        niche_description="Autonomous Whop short-form creator video tests."
    )
    return p_id


@pytest.fixture
def test_campaign(repo, test_project):
    c_id = f"test_camp_{uuid.uuid4().hex[:8]}"
    repo.create_campaign(
        campaign_id=c_id,
        project_id=test_project,
        name="Integrity Audit Campaign",
        status="active"
    )
    return c_id


@pytest.mark.skipif(not check_db_connection(), reason="PostgreSQL is not reachable")
class TestDatabaseIntegrity:
    """Automated verification of PostgreSQL persistence, relationships, and error handling."""

    def test_1_video_persists(self, repo, test_project):
        """1. Video persists in videos table with project relationship."""
        v_id = f"vid_test_{uuid.uuid4().hex[:8]}"
        created = repo.register_video(
            video_id=v_id,
            project_id=test_project,
            file_path="/media/test_source.mp4",
            status="registered"
        )
        assert created["id"] == v_id
        assert created["project_id"] == test_project

        fetched = repo.get_video(v_id)
        assert fetched is not None
        assert fetched["id"] == v_id
        assert fetched["file_path"] == "/media/test_source.mp4"
        assert fetched["status"] == "registered"

    def test_2_job_persists(self, repo, test_campaign):
        """2. Job persists in jobs table with campaign and worker relationship."""
        j_id = f"job_test_{uuid.uuid4().hex[:8]}"
        input_data = {"target_word": "growth", "scale": 1.25, "duration_ms": 1200}
        created = repo.create_job(
            job_id=j_id,
            campaign_id=test_campaign,
            job_type="PRODUCTION_EDIT",
            input_data=input_data,
            status="pending"
        )
        assert created["id"] == j_id

        # Update job with worker and output
        repo.update_job(
            job_id=j_id,
            status="completed",
            assigned_worker_id=None,
            output_data={"best_version": 1, "best_score": 8.5}
        )

        fetched = repo.get_job(j_id)
        assert fetched is not None
        assert fetched["id"] == j_id
        assert fetched["status"] == "completed"
        assert fetched["input_data"]["target_word"] == "growth"
        assert fetched["output_data"]["best_score"] == 8.5

    def test_3_gemini_review_persists(self, repo, test_campaign, test_project):
        """3. Gemini review persists in reviews table linked to job and video."""
        v_id = f"vid_test_{uuid.uuid4().hex[:8]}"
        repo.register_video(video_id=v_id, project_id=test_project, file_path="/media/test.mp4")

        j_id = f"job_test_{uuid.uuid4().hex[:8]}"
        repo.create_job(job_id=j_id, campaign_id=test_campaign, job_type="EDIT", input_data={})

        rev_id = f"rev_test_{uuid.uuid4().hex[:8]}"
        repo.record_review(
            review_id=rev_id,
            job_id=j_id,
            video_id=v_id,
            attempt=1,
            reviewer_type="GeminiBrowserReviewer",
            verdict="FAIL",
            overall_score=4.5,
            scores={"timing_score": 4.0, "visual_quality": 5.0},
            problems=[{"type": "framing", "description": "Punch-in slightly off-center."}],
            corrections=["Adjust framing scale and timing."]
        )

        reviews = repo.get_reviews_for_job(j_id)
        assert len(reviews) == 1
        assert reviews[0]["id"] == rev_id
        assert reviews[0]["overall_score"] == 4.5
        assert reviews[0]["verdict"] == "FAIL"

    def test_4_correction_persists(self, repo, test_campaign, test_project):
        """4. Review corrections are stored and retrievable as structured lists."""
        v_id = f"vid_test_{uuid.uuid4().hex[:8]}"
        repo.register_video(video_id=v_id, project_id=test_project, file_path="/media/test.mp4")

        j_id = f"job_test_{uuid.uuid4().hex[:8]}"
        repo.create_job(job_id=j_id, campaign_id=test_campaign, job_type="EDIT", input_data={})

        corrections_list = [
            "Increase punch-in scale from 1.20x to 1.25x",
            "Extend effect duration by 200ms"
        ]
        rev_id = f"rev_test_{uuid.uuid4().hex[:8]}"
        repo.record_review(
            review_id=rev_id,
            job_id=j_id,
            video_id=v_id,
            attempt=1,
            reviewer_type="GeminiBrowserReviewer",
            verdict="FAIL",
            overall_score=4.5,
            corrections=corrections_list
        )

        reviews = repo.get_reviews_for_job(j_id)
        assert len(reviews) == 1
        assert reviews[0]["corrections"] == corrections_list

    def test_5_version_relationship_persists(self, repo, test_campaign, test_project):
        """5. Multiple review iterations (v1, v2, v3) are preserved in order and distinguishable."""
        v_id = f"vid_test_{uuid.uuid4().hex[:8]}"
        repo.register_video(video_id=v_id, project_id=test_project, file_path="/media/test.mp4")

        j_id = f"job_test_{uuid.uuid4().hex[:8]}"
        repo.create_job(job_id=j_id, campaign_id=test_campaign, job_type="EDIT", input_data={})

        for attempt, score in [(1, 4.5), (2, 6.0), (3, 7.5)]:
            repo.record_review(
                review_id=f"rev_{j_id}_v{attempt}",
                job_id=j_id,
                video_id=v_id,
                attempt=attempt,
                reviewer_type="GeminiBrowserReviewer",
                verdict="FAIL" if score < 10.0 else "PASS",
                overall_score=score
            )

        reviews = repo.get_reviews_for_job(j_id)
        assert len(reviews) == 3
        attempts = [r["attempt"] for r in reviews]
        scores = [r["overall_score"] for r in reviews]
        assert attempts == [1, 2, 3]
        assert scores == [4.5, 6.0, 7.5]

    def test_6_evidence_persists(self, repo, test_project):
        """6. Evidence persists and links to both knowledge and video records."""
        v_id = f"vid_test_{uuid.uuid4().hex[:8]}"
        repo.register_video(video_id=v_id, project_id=test_project, file_path="/media/test.mp4")

        k_id = f"know_test_{uuid.uuid4().hex[:8]}"
        repo.create_knowledge_candidate(
            knowledge_id=k_id,
            project_id=test_project,
            event_type="EDIT_TEST",
            action_type="PUNCH_IN",
            parameters_json=json.dumps({"scale": 1.25})
        )

        ev_id = f"evid_test_{uuid.uuid4().hex[:8]}"
        repo.record_evidence(
            evidence_id=ev_id,
            knowledge_id=k_id,
            video_id=v_id,
            outcome_note="Tested scale 1.25x with positive viewer response",
            metric_value=8.8
        )

        with transaction_scope() as cur:
            cur.execute("SELECT id, knowledge_id, video_id, metric_value FROM evidence WHERE id = %s", (ev_id,))
            row = cur.fetchone()
            assert row is not None
            assert row[0] == ev_id
            assert row[1] == k_id
            assert row[2] == v_id
            assert row[3] == 8.8

    def test_7_knowledge_persists(self, repo, test_project):
        """7. Knowledge persists with scoped parameters, status, confidence, and sample size."""
        k_id = f"know_test_{uuid.uuid4().hex[:8]}"
        repo.create_knowledge_candidate(
            knowledge_id=k_id,
            project_id=test_project,
            event_type="PUNCH_IN_EVAL",
            action_type="PUNCH_IN_PARAMS",
            parameters_json=json.dumps({"scale": 1.22, "duration_ms": 1150}),
            confidence=0.45,
            sample_size=1
        )

        fetched = repo.get_knowledge(k_id)
        assert fetched is not None
        assert fetched["project_id"] == test_project
        assert fetched["status"] == "candidate"
        assert fetched["confidence"] == 0.45
        assert fetched["sample_size"] == 1

        # Promote knowledge
        updated = repo.update_knowledge(
            knowledge_id=k_id,
            status="validated",
            confidence=0.75,
            sample_size=3
        )
        assert updated["status"] == "validated"
        assert updated["confidence"] == 0.75
        assert updated["sample_size"] == 3

    def test_8_worker_state_persists(self, repo):
        """8. Worker state persists in workers table across updates."""
        w_id = f"worker_test_{uuid.uuid4().hex[:8]}"
        repo.register_worker(
            worker_id=w_id,
            provider="flow_gemini",
            capabilities=["REVIEW", "EDITING"],
            status="available",
            metadata={"profile_id": "flow_profile_2", "priority": 1}
        )

        fetched = repo.get_worker(w_id)
        assert fetched is not None
        assert fetched["provider"] == "flow_gemini"
        assert fetched["status"] == "available"
        assert fetched["metadata"]["profile_id"] == "flow_profile_2"

        # Update status
        repo.update_worker_status(worker_id=w_id, status="busy", current_job_id="job_xyz")
        updated = repo.get_worker(w_id)
        assert updated["status"] == "busy"
        assert updated["current_job_id"] == "job_xyz"

    def test_9_audit_event_persists(self, repo):
        """9. Audit log persists immutable event records."""
        a_id = f"audit_test_{uuid.uuid4().hex[:8]}"
        repo.log_audit(
            audit_id=a_id,
            action="TEST_ACTION",
            target="target_entity_01",
            detail="Auditing PostgreSQL persistent write capability."
        )

        with transaction_scope() as cur:
            cur.execute("SELECT id, action, target, detail FROM audit_log WHERE id = %s", (a_id,))
            row = cur.fetchone()
            assert row is not None
            assert row[0] == a_id
            assert row[1] == "TEST_ACTION"
            assert row[2] == "target_entity_01"

    def test_10_read_back_works_after_process_restart(self, test_project):
        """10. Independent repository instance can read back all state created by previous instance."""
        v_id = f"vid_restart_{uuid.uuid4().hex[:8]}"
        j_id = f"job_restart_{uuid.uuid4().hex[:8]}"

        # Instance 1 writes
        repo1 = DatabaseRepository()
        repo1.register_video(video_id=v_id, project_id=test_project, file_path="/media/restart.mp4")
        repo1.create_job(job_id=j_id, campaign_id=None, job_type="TEST", input_data={"val": 42})
        del repo1

        # Instance 2 (simulating fresh process) reads
        repo2 = DatabaseRepository()
        v = repo2.get_video(v_id)
        j = repo2.get_job(j_id)
        assert v is not None and v["id"] == v_id
        assert j is not None and j["id"] == j_id
        assert j["input_data"]["val"] == 42

    def test_11_orphan_relationships_prevented(self, repo):
        """11. Foreign key constraints reject orphan child entities."""
        non_existent = f"ghost_{uuid.uuid4().hex[:8]}"

        # Orphan video
        with pytest.raises(ForeignKeyMissingError):
            repo.register_video(video_id=f"v_{uuid.uuid4().hex[:6]}", project_id=non_existent, file_path="x.mp4")

        # Orphan campaign
        with pytest.raises(ForeignKeyMissingError):
            repo.create_campaign(campaign_id=f"c_{uuid.uuid4().hex[:6]}", project_id=non_existent, name="Ghost")

        # Orphan job with invalid campaign
        with pytest.raises(ForeignKeyMissingError):
            repo.create_job(job_id=f"j_{uuid.uuid4().hex[:6]}", campaign_id=non_existent, job_type="EDIT", input_data={})

        # Orphan review with invalid job
        with pytest.raises(ForeignKeyMissingError):
            repo.record_review(
                review_id=f"r_{uuid.uuid4().hex[:6]}",
                job_id=non_existent,
                video_id=None,
                attempt=1,
                reviewer_type="Gemini",
                verdict="FAIL"
            )

        # Orphan evidence with invalid knowledge
        with pytest.raises(ForeignKeyMissingError):
            repo.record_evidence(
                evidence_id=f"e_{uuid.uuid4().hex[:6]}",
                knowledge_id=non_existent,
                video_id=None,
                outcome_note="Ghost note"
            )

    def test_12_duplicate_accidental_persistence_prevented(self, repo, test_project):
        """12. Unique primary key constraints prevent duplicate accidental record insertion."""
        p_dup = f"proj_dup_{uuid.uuid4().hex[:8]}"
        repo.create_project(project_id=p_dup, name="First", niche_description="Desc")

        with pytest.raises(DuplicateEntityError):
            repo.create_project(project_id=p_dup, name="Second", niche_description="Desc")

        v_dup = f"vid_dup_{uuid.uuid4().hex[:8]}"
        repo.register_video(video_id=v_dup, project_id=p_dup, file_path="dup.mp4")
        with pytest.raises(DuplicateEntityError):
            repo.register_video(video_id=v_dup, project_id=p_dup, file_path="dup2.mp4")

    def test_13_database_failure_surfaced(self, monkeypatch):
        """13. Database connectivity failures raise clean, explicit exceptions rather than silently swallowing."""
        from db.connection import get_raw_connection
        from config import settings

        # Monkeypatch database port to unroutable port
        monkeypatch.setattr(settings, "DB_PORT", 59998)
        with pytest.raises(DatabaseConnectionError) as excinfo:
            get_raw_connection()
        assert "Could not connect to PostgreSQL" in str(excinfo.value)
