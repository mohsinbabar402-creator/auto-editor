"""
Creative Intelligence Engine — Shared Data Models

Every structured object that flows between brain subsystems is defined here.
No module should invent its own ad-hoc dict schema.
All fields are explicit and documented.
"""

from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


# ─── Enumerations ────────────────────────────────────────────────────────────

class ContentType(Enum):
    """What kind of moment the candidate represents."""
    STRONG_OPINION = "strong_opinion"
    STORY = "story"
    ADVICE = "advice"
    REVELATION = "revelation"
    DEBATE = "debate"
    HUMOR = "humor"
    EMOTIONAL = "emotional"
    TECHNICAL = "technical"
    CONFLICT = "conflict"
    PERSONAL_EXPERIENCE = "personal_experience"


class ContextSafety(Enum):
    """Whether the clip can stand alone without distorting meaning."""
    SAFE = "safe"
    QUESTIONABLE = "questionable"
    CONTEXT_REQUIRED = "context_required"
    MISLEADING = "misleading"
    REJECT = "reject"


class ClaimType(Enum):
    """Classification of factual-looking statements."""
    FACTUAL_FROM_SOURCE = "factual_from_source"
    OPINION = "opinion"
    PERSONAL_EXPERIENCE = "personal_experience"
    SPECULATION = "speculation"
    UNVERIFIED_CLAIM = "unverified_claim"
    CONTEXT_REQUIRED = "context_required"
    MISLEADING_RISK = "misleading_risk"
    REJECT = "reject"


class HookMechanism(Enum):
    """Available hook strategies."""
    CURIOSITY_GAP = "curiosity_gap"
    OPEN_LOOP = "open_loop"
    CONTRARIAN = "contrarian"
    CONFLICT_FIRST = "conflict_first"
    OUTCOME_FIRST = "outcome_first"
    STRONG_CLAIM = "strong_claim"
    QUESTION = "question"
    CHALLENGE = "challenge"
    UNEXPECTED_REVELATION = "unexpected_revelation"
    EMOTIONAL_TENSION = "emotional_tension"
    STATUS_CONFLICT = "status_conflict"
    CONSEQUENCE = "consequence"
    STORY_OPENING = "story_opening"
    INTRIGUING_QUOTE = "intriguing_quote"
    PAYOFF_PREVIEW = "payoff_preview"


class CandidateStatus(Enum):
    """Lifecycle status of a candidate clip."""
    DISCOVERED = "discovered"
    ANALYZING = "analyzing"
    CANDIDATE = "candidate"
    SELECTED = "selected"
    PLANNED = "planned"
    PRODUCING = "producing"
    RENDERED = "rendered"
    QA_PASS = "qa_pass"
    QA_FAIL = "qa_fail"
    REPAIRING = "repairing"
    APPROVED = "approved"
    PUBLISHED = "published"
    REJECTED = "rejected"
    FAILED = "failed"


class PauseType(Enum):
    """Classification of silence in speech."""
    UNNECESSARY = "unnecessary"
    NATURAL = "natural"
    EMOTIONAL = "emotional"
    DRAMATIC = "dramatic"
    THOUGHTFUL = "thoughtful"


# ─── Core Data Structures ───────────────────────────────────────────────────

@dataclass
class SRTEntry:
    """A single subtitle entry parsed from an SRT file."""
    index: int
    start_sec: float
    end_sec: float
    text: str


@dataclass
class DialogueSegment:
    """A continuous stretch of speech by one speaker on one topic."""
    start_sec: float
    end_sec: float
    speaker: str
    text: str
    topic: str = ""
    emotion: str = "neutral"


@dataclass
class TopicSegment:
    """A thematic section of the episode spanning multiple dialogue segments."""
    topic: str
    summary: str
    start_sec: float
    end_sec: float
    speakers: List[str] = field(default_factory=list)
    key_claims: List[str] = field(default_factory=list)
    emotional_arc: str = "neutral"
    segments: List[DialogueSegment] = field(default_factory=list)


@dataclass
class SourceAnalysis:
    """Complete semantic understanding of a source episode."""
    source_id: str
    title: str
    url: str
    total_duration_sec: float
    speakers: List[str]
    topics: List[TopicSegment]
    raw_entries: List[SRTEntry]
    dialogue_segments: List[DialogueSegment]
    summary: str = ""


@dataclass
class VirialityScores:
    """Multi-vector scoring for a candidate clip."""
    hook_potential: float = 0.0       # 0-10
    curiosity: float = 0.0           # 0-10
    novelty: float = 0.0             # 0-10
    emotional_intensity: float = 0.0  # 0-10
    story_quality: float = 0.0       # 0-10
    payoff_strength: float = 0.0     # 0-10
    shareability: float = 0.0        # 0-10
    comment_potential: float = 0.0   # 0-10
    audience_relevance: float = 0.0  # 0-10
    practical_value: float = 0.0     # 0-10
    visual_potential: float = 0.0    # 0-10
    platform_fit: float = 0.0       # 0-10
    context_completeness: float = 0.0 # 0-10
    speaker_credibility: float = 0.0  # 0-10

    @property
    def weighted_total(self) -> float:
        """Compute weighted aggregate. Hook and context have highest weight."""
        weights = {
            'hook_potential': 2.0,
            'curiosity': 1.5,
            'novelty': 1.0,
            'emotional_intensity': 1.2,
            'story_quality': 1.3,
            'payoff_strength': 1.8,
            'shareability': 1.0,
            'comment_potential': 0.8,
            'audience_relevance': 1.2,
            'practical_value': 1.0,
            'visual_potential': 0.5,
            'platform_fit': 0.8,
            'context_completeness': 2.0,
            'speaker_credibility': 0.9,
        }
        total = 0.0
        weight_sum = 0.0
        for attr, w in weights.items():
            total += getattr(self, attr) * w
            weight_sum += w
        return round(total / weight_sum, 2) if weight_sum > 0 else 0.0


@dataclass
class NegativeFactors:
    """Risk factors that penalize or disqualify a candidate."""
    boring: float = 0.0              # 0-10 (higher = more boring)
    repetitive: float = 0.0
    context_dependent: float = 0.0
    misleading_risk: float = 0.0
    weak_payoff: float = 0.0
    excessive_length: float = 0.0
    poor_audio: float = 0.0
    filler_heavy: float = 0.0

    @property
    def has_critical_failure(self) -> bool:
        """Any single negative factor at 8+ is a hard fail."""
        return any(v >= 8.0 for v in [
            self.misleading_risk,
            self.boring,
            self.weak_payoff,
        ])


@dataclass
class ClipCandidate:
    """A potential clip discovered from the source."""
    candidate_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    source_id: str = ""
    start_sec: float = 0.0
    end_sec: float = 0.0
    transcript: str = ""
    speakers: List[str] = field(default_factory=list)
    topic: str = ""
    content_type: ContentType = ContentType.STRONG_OPINION
    context_before: str = ""
    context_after: str = ""
    context_safety: ContextSafety = ContextSafety.SAFE
    claims: List[Dict[str, Any]] = field(default_factory=list)
    scores: VirialityScores = field(default_factory=VirialityScores)
    negatives: NegativeFactors = field(default_factory=NegativeFactors)
    recommended_duration_sec: float = 0.0
    confidence: float = 0.0
    status: CandidateStatus = CandidateStatus.DISCOVERED
    rejection_reason: str = ""

    @property
    def duration_sec(self) -> float:
        return round(self.end_sec - self.start_sec, 2)

    @property
    def final_score(self) -> float:
        if self.negatives.has_critical_failure:
            return 0.0
        if self.context_safety in (ContextSafety.MISLEADING, ContextSafety.REJECT):
            return 0.0
        penalty = (self.negatives.boring + self.negatives.weak_payoff +
                   self.negatives.context_dependent + self.negatives.misleading_risk) / 40.0
        return round(max(0, self.scores.weighted_total * (1.0 - penalty)), 2)


@dataclass
class HookCandidate:
    """A single generated hook variant for a clip."""
    mechanism: HookMechanism = HookMechanism.CURIOSITY_GAP
    text: str = ""
    header_text: str = ""
    voice_id: str = "en-US-ChristopherNeural"
    estimated_duration_sec: float = 5.0
    truthfulness_score: float = 0.0  # 0-10, must be >= 7 to pass
    hook_strength: float = 0.0      # 0-10
    reasoning: str = ""

    @property
    def is_truthful(self) -> bool:
        return self.truthfulness_score >= 7.0

    @property
    def is_viable(self) -> bool:
        return self.is_truthful and self.hook_strength >= 5.0


@dataclass
class HookSelection:
    """The brain's final hook decision for a clip."""
    candidate_id: str = ""
    variants: List[HookCandidate] = field(default_factory=list)
    selected: Optional[HookCandidate] = None
    selection_reasoning: str = ""


@dataclass
class EditPlan:
    """Complete editorial decision document generated BEFORE rendering."""
    candidate_id: str = ""
    hook: Optional[HookCandidate] = None
    target_platform: str = "youtube_shorts"
    layout_style: str = "ambient_blur"
    body_start_sec: float = 0.0
    body_end_sec: float = 0.0
    target_duration_sec: float = 60.0
    editing_necessity: float = 0.5  # 0.0 (Minimal/None) -> 1.0 (Heavy Dynamic)
    pacing_notes: str = ""
    silence_decisions: List[Dict[str, Any]] = field(default_factory=list)
    filler_plan: List[Dict[str, Any]] = field(default_factory=list)
    punch_in_plan: List[Dict[str, Any]] = field(default_factory=list)
    broll_decisions: List[Dict[str, Any]] = field(default_factory=list)
    caption_emphasis_words: List[str] = field(default_factory=list)
    audio_treatment: str = "NATURAL_BALANCED"
    music_treatment: str = "NONE"  # NONE, SUBTLE_AMBIENT_DUCKED, MODERATE
    sfx_plan: List[Dict[str, Any]] = field(default_factory=list)
    cta_text: str = ""  # Empty string when ending_strategy is NO_CTA or NATURAL_END
    ending_strategy: str = "NATURAL_END"  # NATURAL_END, PAYOFF_END, LOOP_END, QUESTION_END, CLIFFHANGER, CTA, NO_CTA


@dataclass
class QACheck:
    """A single QA check result with structured forensic evidence."""
    name: str = ""
    category: str = ""         # TECHNICAL, AUDIO, VIDEO, CAPTIONS, CONTENT, EDIT_PLAN_COMPLIANCE
    method: str = "DETERMINISTIC"  # DETERMINISTIC, HEURISTIC, NOT_IMPLEMENTED
    passed: bool = True
    severity: str = "INFO"     # INFO, WARNING, HARD_FAIL
    expected: str = ""
    actual: str = ""
    timestamp_range: str = ""  # e.g. '00:04.20 - 00:07.10'
    measured_value: str = ""   # e.g. 'luminance: 2.3', 'volume: +0.4dB'
    threshold: str = ""        # e.g. 'min_luminance: 8.0'
    evidence: str = ""
    repair_action: str = ""    # RENDER_RETRY, AUDIO_REMASTER, REGENERATE_CAPTIONS, etc.
    repair_safety: str = ""    # SAFE_TO_AUTOFIX, REQUIRES_RE_RENDER, REQUIRES_EDITORIAL_REVIEW, NOT_AUTOMATABLE

@dataclass
class QAResult:
    """Result of Red-Team QA inspection on a rendered video."""
    render_id: str = ""
    passed: bool = False
    score: float = 0.0
    hard_fails: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    checks_run: List[QACheck] = field(default_factory=list)
    video_score: float = 0.0       # 0-100
    audio_score: float = 0.0       # 0-100
    caption_score: float = 0.0     # 0-100
    content_score: float = 0.0     # 0-100
    compliance_score: float = 0.0  # 0-100 (EditPlan compliance)
    confidence: float = 0.0        # 0-1.0 (how confident QA is in this result)
    recommended_action: str = "approve"  # approve, repair, reject
    repair_instructions: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class RepairRecord:
    """Log of a single repair attempt."""
    render_id: str = ""
    attempt_number: int = 1
    problem: str = ""
    root_cause: str = ""
    action_taken: str = ""
    expected_result: str = ""
    actual_result: str = ""
    resolved: bool = False


@dataclass
class CreativeDecisionRecord:
    """Complete audit trail for a produced clip."""
    candidate: Optional[ClipCandidate] = None
    hook_selection: Optional[HookSelection] = None
    edit_plan: Optional[EditPlan] = None
    qa_results: List[QAResult] = field(default_factory=list)
    repairs: List[RepairRecord] = field(default_factory=list)
    final_status: str = ""
    final_cloud_path: str = ""
