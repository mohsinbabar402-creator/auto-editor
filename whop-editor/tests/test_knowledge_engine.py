import unittest
import uuid
from db.connection import transaction_scope
from db.repository import DatabaseRepository
from learning.knowledge_engine import KnowledgeEngine, KnowledgeStatus


class TestKnowledgeEngine(unittest.TestCase):

    def setUp(self):
        self.repo = DatabaseRepository()
        self.engine = KnowledgeEngine(self.repo)
        self.project_id = f"proj_test_{uuid.uuid4().hex[:8]}"

        with transaction_scope() as cur:
            cur.execute("INSERT INTO projects (id, name, niche_description) VALUES (%s, %s, %s);",
                        (self.project_id, "Test Learn Project", "Short form testing"))

    def tearDown(self):
        with transaction_scope() as cur:
            cur.execute("DELETE FROM evidence WHERE knowledge_id IN (SELECT id FROM knowledge WHERE project_id = %s);", (self.project_id,))
            cur.execute("DELETE FROM knowledge WHERE project_id = %s;", (self.project_id,))
            cur.execute("DELETE FROM projects WHERE id = %s;", (self.project_id,))

    def test_default_fallback_parameters(self):
        params = self.engine.get_validated_parameters(self.project_id)
        self.assertIn("scale", params)
        self.assertIn("duration_ms", params)

    def test_record_edit_outcome_rejection(self):
        outcome = self.engine.record_edit_outcome(
            project_id=self.project_id,
            video_id=None,
            event_type="PUNCH_IN_EDIT",
            action_type="PUNCH_IN_PARAMS",
            parameters={"scale": 1.10, "duration_ms": 600},
            approved=False,
            score=4.0,
            outcome_note="Rejected due to weak punch-in framing"
        )
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome["status"], KnowledgeStatus.CANDIDATE.value)
        self.assertLessEqual(outcome["confidence"], 0.35)

    def test_record_edit_outcome_repeated_approval_promotes_to_validated(self):
        test_params = {"scale": 1.22, "duration_ms": 1050}

        # 1st approval
        k1 = self.engine.record_edit_outcome(
            project_id=self.project_id,
            video_id=None,
            event_type="PUNCH_IN_EDIT",
            action_type="PUNCH_IN_PARAMS",
            parameters=test_params,
            approved=True,
            score=8.0,
            outcome_note="1st approval"
        )
        self.assertGreaterEqual(k1["confidence"], 0.5)

        # 2nd approval
        k2 = self.engine.record_edit_outcome(
            project_id=self.project_id,
            video_id=None,
            event_type="PUNCH_IN_EDIT",
            action_type="PUNCH_IN_PARAMS",
            parameters=test_params,
            approved=True,
            score=9.0,
            outcome_note="2nd approval with high score"
        )
        self.assertEqual(k2["status"], KnowledgeStatus.VALIDATED.value)
        self.assertGreaterEqual(k2["confidence"], 0.65)
        self.assertEqual(k2["sample_size"], 2)

        # Retrieval should now return the validated parameters
        retrieved = self.engine.get_validated_parameters(self.project_id)
        self.assertEqual(retrieved["scale"], 1.22)
        self.assertEqual(retrieved["duration_ms"], 1050)


if __name__ == "__main__":
    unittest.main()
