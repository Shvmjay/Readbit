"""Import all models so SQLAlchemy metadata (and Alembic) sees every table."""

from app.models.books import Book, Chapter, DocumentChunk, EvidenceReference, ProcessingJob, SourceFile
from app.models.content import Annotation, ReadingState, Summary, SummaryEvidence
from app.models.learning import (
    Achievement,
    Question,
    QuestionAttempt,
    QuizSession,
    SessionQuestion,
    Topic,
    TopicMastery,
    UserAchievement,
)
from app.models.ops import AIExecution, AnalyticsEvent
from app.models.users import AuthSession, GuestSession, PasswordResetToken, User

__all__ = [
    "AIExecution",
    "Achievement",
    "AnalyticsEvent",
    "Annotation",
    "AuthSession",
    "Book",
    "Chapter",
    "DocumentChunk",
    "EvidenceReference",
    "GuestSession",
    "PasswordResetToken",
    "ProcessingJob",
    "Question",
    "QuestionAttempt",
    "QuizSession",
    "ReadingState",
    "SessionQuestion",
    "SourceFile",
    "Summary",
    "SummaryEvidence",
    "Topic",
    "TopicMastery",
    "User",
    "UserAchievement",
]
