"""Tests for question pool selection logic."""
from src.core.question_pools import (
    QuestionSelector,
    ChallengeQuestion,
    ALL_QUESTIONS,
)


class TestQuestionSelector:
    def setup_method(self):
        self.selector = QuestionSelector()

    def test_select_questions_default(self):
        """Fresh target, no domain filter → returns up to 10 questions."""
        questions = self.selector.select_questions("target-1")
        assert len(questions) <= 10
        assert len(questions) > 0
        assert all(isinstance(q, ChallengeQuestion) for q in questions)

    def test_select_questions_count(self):
        """count=3 → exactly 3 returned."""
        questions = self.selector.select_questions("target-2", count=3)
        assert len(questions) == 3

    def test_select_questions_domain_filter(self):
        """domains=["defi"] → all returned questions have domain=="defi"."""
        questions = self.selector.select_questions("target-3", domains=["defi"], count=3)
        assert all(q.domain == "defi" for q in questions)

    def test_select_questions_no_repeat(self):
        """Call twice for same target → no overlap."""
        q1 = self.selector.select_questions("target-4", count=3)
        q2 = self.selector.select_questions("target-4", count=3)
        ids1 = {q.id for q in q1}
        ids2 = {q.id for q in q2}
        assert ids1.isdisjoint(ids2), "Second selection should not repeat questions"

    def test_select_questions_exhaustion_reset(self):
        """Call enough times to exhaust pool → resets and keeps working."""
        total = len(ALL_QUESTIONS)
        # Ask for all questions, then ask again — should reset
        q1 = self.selector.select_questions("target-5", count=total)
        assert len(q1) == total
        q2 = self.selector.select_questions("target-5", count=3)
        assert len(q2) == 3  # Pool reset, can select again


class TestChallengeQuestion:
    def test_question_weight(self):
        """easy=1, medium=2, hard=3."""
        easy = ChallengeQuestion(question="q", domain="d", difficulty="easy", reference_answer="a")
        medium = ChallengeQuestion(question="q", domain="d", difficulty="medium", reference_answer="a")
        hard = ChallengeQuestion(question="q", domain="d", difficulty="hard", reference_answer="a")
        assert easy.weight == 1
        assert medium.weight == 2
        assert hard.weight == 3

    def test_question_id_deterministic(self):
        """Same question text → same SHA256 ID."""
        q1 = ChallengeQuestion(question="What is DeFi?", domain="defi", difficulty="easy", reference_answer="a")
        q2 = ChallengeQuestion(question="What is DeFi?", domain="defi", difficulty="easy", reference_answer="b")
        assert q1.id == q2.id

    def test_all_questions_have_required_fields(self):
        """Iterate ALL_QUESTIONS: all required fields present."""
        for q in ALL_QUESTIONS:
            assert q.question, f"Question missing text: {q}"
            assert q.domain, f"Question missing domain: {q}"
            assert q.difficulty in ("easy", "medium", "hard"), f"Invalid difficulty: {q.difficulty}"
            assert q.reference_answer, f"Question missing reference_answer: {q}"
            assert q.category, f"Question missing category: {q}"
