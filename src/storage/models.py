"""Pydantic models for Quality Oracle data."""
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class TargetType(str, Enum):
    MCP_SERVER = "mcp_server"
    AGENT = "agent"
    SKILL = "skill"


class EvalStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EvalLevel(int, Enum):
    MANIFEST = 1
    FUNCTIONAL = 2
    DOMAIN_EXPERT = 3


class QualityTier(str, Enum):
    EXPERT = "expert"
    PROFICIENT = "proficient"
    BASIC = "basic"
    FAILED = "failed"


# Request models
class EvaluateRequest(BaseModel):
    target_url: str
    target_type: TargetType = TargetType.MCP_SERVER
    level: EvalLevel = EvalLevel.FUNCTIONAL
    domains: List[str] = []
    webhook_url: Optional[str] = None


# Response models
class EvaluateResponse(BaseModel):
    evaluation_id: str
    status: EvalStatus = EvalStatus.PENDING
    estimated_time_seconds: int = 60


class ToolScore(BaseModel):
    score: int
    tests_passed: int
    tests_total: int


class ScoreResponse(BaseModel):
    target_id: str
    target_type: TargetType
    score: int = 0
    tier: QualityTier = QualityTier.FAILED
    confidence: float = 0.0
    domains: List[str] = []
    tool_scores: Dict[str, ToolScore] = {}
    evaluation_count: int = 0
    last_evaluated_at: Optional[datetime] = None
    attestation_url: Optional[str] = None


class EvaluationStatus(BaseModel):
    evaluation_id: str
    status: EvalStatus
    progress_pct: int = 0
    result: Optional[ScoreResponse] = None
    error: Optional[str] = None


# Database document models
class EvaluationDoc(BaseModel):
    target_id: str
    target_type: TargetType
    target_url: str
    target_manifest: Optional[dict] = None
    status: EvalStatus = EvalStatus.PENDING
    level: EvalLevel = EvalLevel.FUNCTIONAL
    questions_asked: int = 0
    questions_answered: int = 0
    scores: Optional[dict] = None
    llm_judge_model: Optional[str] = None
    llm_judge_responses: List[dict] = []
    attestation_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None


class ScoreDoc(BaseModel):
    target_id: str
    target_type: TargetType
    current_score: int = 0
    tier: QualityTier = QualityTier.FAILED
    confidence: float = 0.0
    evaluation_count: int = 0
    trend: str = "stable"  # improving, stable, declining
    domain_scores: Dict[str, dict] = {}
    tool_scores: Dict[str, dict] = {}
    last_evaluated_at: Optional[datetime] = None
    next_evaluation_at: Optional[datetime] = None
    badge_url: Optional[str] = None
