import pytest
import uuid
from db.repository import DatabaseRepository, EntityNotFoundError, ForeignKeyMissingError
from campaigns.manager import CampaignManager
from workers.models import JobStatus, Worker, WorkerStatus, ProductionJob
from workers.base import BaseWorker, WorkerPool


class MockCampaignWorker(BaseWorker):
    def __init__(self, worker_id: str = "w_mock_camp"):
        model = Worker(
            id=worker_id,
            provider="mock_camp_provider",
            capabilities=["PRODUCTION_EDIT", "RENDER"],
            status=WorkerStatus.AVAILABLE
        )
        super().__init__(model)

    def execute(self, job: ProductionJob) -> ProductionJob:
        job.status = JobStatus.COMPLETED
        job.output_data = {"rendered_file": "campaign_test_out.mp4", "qc_passed": True}
        return job


@pytest.fixture
def repo():
    return DatabaseRepository()


@pytest.fixture
def test_project(repo):
    p_id = f"proj_camp_test_{uuid.uuid4().hex[:6]}"
    repo.create_project(p_id, "Test Project", "Testing campaigns")
    return p_id


def test_campaign_crud(repo, test_project):
    mgr = CampaignManager(repo=repo)
    camp = mgr.create_campaign(
        project_id=test_project,
        name="Whop Growth Hack Campaign",
        config={"target_audience": "creators", "hook_style": "direct"}
    )
    assert camp.id.startswith("camp_")
    assert camp.name == "Whop Growth Hack Campaign"
    assert camp.config["target_audience"] == "creators"

    # Retrieve
    fetched = mgr.get_campaign(camp.id)
    assert fetched is not None
    assert fetched.name == camp.name

    # List
    camps = mgr.list_campaigns(project_id=test_project)
    assert len(camps) >= 1
    assert any(c.id == camp.id for c in camps)


def test_multi_campaign_isolation(repo, test_project):
    mgr = CampaignManager(repo=repo)
    c1 = mgr.create_campaign(project_id=test_project, name="Campaign Alpha")
    c2 = mgr.create_campaign(project_id=test_project, name="Campaign Beta")

    assert c1.id != c2.id
    camps = mgr.list_campaigns(project_id=test_project)
    camp_ids = [c.id for c in camps]
    assert c1.id in camp_ids
    assert c2.id in camp_ids


def test_campaign_job_creation_and_execution(repo, test_project):
    pool = WorkerPool(max_concurrent_workers=1)
    worker = MockCampaignWorker("w_test_exec")
    pool.register_worker(worker)

    mgr = CampaignManager(repo=repo, worker_pool=pool)
    camp = mgr.create_campaign(project_id=test_project, name="Job Execution Campaign")

    # Create job
    job = mgr.create_production_job(
        campaign_id=camp.id,
        input_video_path="dummy_input.mp4",
        job_type="PRODUCTION_EDIT"
    )
    assert job.status == JobStatus.PENDING
    assert job.campaign_id == camp.id

    # Execute job
    executed = mgr.execute_job(job.id)
    assert executed.status == JobStatus.COMPLETED
    assert executed.output_data["qc_passed"] is True

    # Verify state in DB
    db_job = repo.get_job(job.id)
    assert db_job["status"] == JobStatus.COMPLETED
    assert db_job["output_data"]["rendered_file"] == "campaign_test_out.mp4"
