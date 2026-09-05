import unittest
from analysis.feedback_interpreter import FeedbackInterpreter, IssueType, CorrectionSource, StructuredCorrectionPlan


class TestFeedbackInterpreter(unittest.TestCase):

    def test_interpret_user_framing_tighten(self):
        plan = FeedbackInterpreter.interpret_user_feedback(
            feedback_text="Framing is too wide, punch in tighter on the speaker",
            current_scale=1.15
        )
        self.assertEqual(plan.issue_type, IssueType.FRAMING)
        self.assertGreater(plan.scale_adjustment, 1.15)
        self.assertEqual(plan.source, CorrectionSource.USER_FEEDBACK)
        self.assertGreaterEqual(plan.confidence, 0.7)

    def test_interpret_user_framing_pull_back(self):
        plan = FeedbackInterpreter.interpret_user_feedback(
            feedback_text="That zoom looks weird, it's too tight on his face",
            current_scale=1.28
        )
        self.assertEqual(plan.issue_type, IssueType.FRAMING)
        self.assertLess(plan.scale_adjustment, 1.28)
        self.assertGreaterEqual(plan.scale_adjustment, FeedbackInterpreter.MIN_SCALE)

    def test_interpret_user_timing_extend(self):
        plan = FeedbackInterpreter.interpret_user_feedback(
            feedback_text="The punch in is too short and abrupt, make it longer",
            current_duration_ms=700
        )
        self.assertEqual(plan.issue_type, IssueType.TIMING)
        self.assertGreater(plan.duration_ms_adjustment, 700)

    def test_interpret_user_overlay_safe_zone(self):
        plan = FeedbackInterpreter.interpret_user_feedback(
            feedback_text="The bottom text overlay is cut off by the phone UI margin",
        )
        self.assertEqual(plan.issue_type, IssueType.OVERLAY)
        self.assertIsNotNone(plan.safe_margin_y)

    def test_interpret_gemini_review_corrections(self):
        corrections = [
            "Adjust punch-in scale to 1.25x for talking head emphasis",
            "Extend punch-in duration to 1100 ms to align with statement"
        ]
        plan = FeedbackInterpreter.interpret_gemini_review(
            corrections=corrections,
            current_scale=1.15,
            current_duration_ms=800
        )
        self.assertEqual(plan.scale_adjustment, 1.25)
        self.assertEqual(plan.duration_ms_adjustment, 1100)
        self.assertEqual(plan.source, CorrectionSource.GEMINI_REVIEW)


if __name__ == "__main__":
    unittest.main()
