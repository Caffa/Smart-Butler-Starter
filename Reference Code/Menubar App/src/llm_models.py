"""Pydantic models for structured LLM outputs (routing, todo, deduction, memory, semantic)."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, RootModel, model_validator

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class RoutingOperation(BaseModel):
    """Single routing operation from the LLM router."""

    type: Literal[
        "use_daily_journal",
        "use_zettel_script",
        "use_zettel_append",
        "use_idea_generator",
        "use_fiction_append",
        "use_experiment_create",
        "use_experiment_log",
        "use_dev_log",
        "use_dev_log_create",
        "use_apple_notes_general",
    ] = Field(..., description="The operation type to execute")
    path: str = Field(
        default="",
        description="File path (for experiment_log, file_append, etc)",
    )
    content: str = Field(
        default="",
        description="Content override (empty = use original)",
    )
    extra_paths: Optional[List[str]] = Field(
        default=None,
        description="For use_experiment_log: other experiment file paths that should receive a block reference to the primary log.",
    )
    summary: Optional[str] = Field(
        default=None,
        description="One-line summary for daily diary when content is empty (used for use_experiment_log, use_dev_log, use_zettel_script when report-notes-save-to-diary-mode is summary or one-liner-summary, or as fallback for context-aware summary).",
    )


class RouterPlan(BaseModel):
    """Complete routing plan with one or more operations."""

    operations: List[RoutingOperation] = Field(
        ...,
        min_length=1,
        description="List of operations to execute. Can return multiple for multi-destination routing.",
    )
    referring_to_other_notes: Optional[bool] = Field(
        default=None,
        description="True if the user is referring to other notes; used with reference resolution.",
    )


# ---------------------------------------------------------------------------
# Reference resolution (pre-router)
# ---------------------------------------------------------------------------


class ReferenceResolutionResponse(BaseModel):
    """Which recent note(s) the user is referring to. Paths must match CONTEXT entries."""

    selected_paths: List[str] = Field(
        default_factory=list,
        description="Full file paths from the CONTEXT list that the user is referring to. Empty if none.",
    )


# ---------------------------------------------------------------------------
# Todo classification
# ---------------------------------------------------------------------------


class TodoItem(BaseModel):
    """Single todo item."""

    text: str = Field(..., description="The todo task text")
    done: bool = Field(default=False, description="Whether task is already completed")


class TodoClassification(BaseModel):
    """Classified todos by timing and type."""

    today: List[TodoItem] = Field(default_factory=list, description="Tasks for today")
    tomorrow: List[TodoItem] = Field(
        default_factory=list, description="Tasks for tomorrow"
    )
    someday: List[TodoItem] = Field(
        default_factory=list, description="Indefinite future tasks"
    )
    principles: List[TodoItem] = Field(
        default_factory=list, description="Habits and guidelines"
    )


# ---------------------------------------------------------------------------
# Deduction pipeline
# ---------------------------------------------------------------------------


class SlugResponse(BaseModel):
    """LLM response: slug for a deduction filename."""

    slug: str = Field(..., description="Short hyphenated slug (3-5 words)")


class SimilarDeductionResponse(BaseModel):
    """LLM response: is new hypothesis similar to an existing one."""

    is_similar: bool = Field(
        ..., description="True if substantially similar to an existing hypothesis"
    )
    similar_index: Optional[int] = Field(
        None, description="Index of matching hypothesis if is_similar"
    )
    reason: Optional[str] = Field(None, description="Brief explanation")


class ShouldMergeResponse(BaseModel):
    """LLM response: should two deduction hypotheses be merged."""

    should_merge: bool = Field(..., description="True if same topic/pattern")
    reason: Optional[str] = Field(None, description="Brief explanation")


class HypothesesResponse(BaseModel):
    """LLM response: list of hypotheses formed from context."""

    hypotheses: List[str] = Field(default_factory=list, description="New hypotheses")


class SearchTermsResponse(BaseModel):
    """LLM response: search terms for evidence gathering."""

    search_terms: List[str] = Field(
        default_factory=list, description="3-5 concrete search terms"
    )


class VerifyResponse(BaseModel):
    """LLM response: is hypothesis supported by evidence."""

    supported: bool = Field(
        ..., description="True if evidence clearly supports hypothesis"
    )
    conclusion: Optional[str] = Field(None, description="One short sentence or reason")


class VerifyWithConfidenceResponse(BaseModel):
    """LLM response: verification with confidence score."""

    supported: bool = Field(..., description="True if evidence supports hypothesis")
    confidence: float = Field(
        0.0, ge=0.0, le=1.0, description="Strength of support 0-1"
    )
    conclusion: Optional[str] = Field(None, description="Concise sentence or reason")


class ReasonResponse(BaseModel):
    """LLM response: single reason/explanation text."""

    reason: Optional[str] = Field(None, description="Explanation text")


# ---------------------------------------------------------------------------
# Memory (preference extraction, Apple Notes, diary triage)
# ---------------------------------------------------------------------------


class MemorySortAction(BaseModel):
    """LLM response: how to sort a memory file from inbox."""

    action: Literal["move_existing", "create_new", "stay_in_inbox"] = Field(
        ..., description="Action to take"
    )
    target_folder: Optional[str] = Field(
        None, description="Existing folder name if move_existing"
    )
    new_folder_name: Optional[str] = Field(
        None, description="New folder name if create_new"
    )


class FoldersResponse(BaseModel):
    """LLM response: picked memory folders for a note."""

    folders: List[str] = Field(
        default_factory=list, description="1-3 relevant folder names"
    )


class AppleNotesMappingResponse(BaseModel):
    """LLM response: pick existing or create new Apple Notes mapping."""

    use_existing: Optional[str] = Field(
        None, description="Relative path of existing file to use"
    )
    create_new: Optional[bool] = Field(
        None, description="Whether to create new mapping"
    )
    new_filename: Optional[str] = Field(None, description="Filename for new mapping")
    topic: Optional[str] = Field(None, description="Topic heading for new file")


class FactWithTags(BaseModel):
    """Single fact with tags."""

    fact: str = Field(..., description="One short statement")
    tags: List[str] = Field(
        default_factory=list, description="Hashtags for searchability"
    )


class FactsResponse(BaseModel):
    """LLM response: extracted facts with tags."""

    facts: List[FactWithTags] = Field(
        default_factory=list, description="Facts with tags"
    )


class RelevantFilesResponse(BaseModel):
    """LLM response: relevant preference filenames."""

    relevant_files: List[str] = Field(
        default_factory=list, description="0-3 exact filenames"
    )


class TagsResponse(BaseModel):
    """LLM response: extracted hashtags."""

    tags: List[str] = Field(default_factory=list, description="Hashtags")


class BrowseIndicesResponse(RootModel[List[int]]):
    """LLM response: JSON array of 1-based file indices (for diary browse).

    Also accepts dict format {"1": true, "3": true} from LLMs that ignore array instructions.
    """

    @model_validator(mode="before")
    @classmethod
    def convert_dict_to_list(cls, data):
        if isinstance(data, dict):
            # Convert {"1": true, "3": true, "5": true} -> [1, 3, 5]
            indices = [int(k) for k in data.keys() if k.isdigit() and data[k]]
            return sorted(indices)
        return data


class TriageActionResponse(BaseModel):
    """LLM response: diary entry triage action."""

    action: Literal["dismiss", "temporal", "preference", "deduction"] = Field(
        ..., description="How to process the entry"
    )
    reasoning: Optional[str] = Field(None, description="Brief explanation")


class PatternMatchResponse(BaseModel):
    """LLM response: does observation match an existing pattern."""

    matches_pattern: bool = Field(..., description="True if matches a known pattern")
    pattern_slug: Optional[str] = Field(
        None, description="Slug of matching pattern file"
    )
    relationship: Optional[str] = Field(None, description="affirms|disproves|none")
    reasoning: Optional[str] = Field(None, description="Brief explanation")


# Apple Notes resolve (note_type, note_name, tag, etc.) - many optional string fields
class ResolveAppleNotesResponse(BaseModel):
    """LLM response: Apple Note name, tag, and optional memory file creation."""

    note_type: Optional[str] = None
    note_name: Optional[str] = None
    tag: Optional[str] = None
    use_memory_file: Optional[str] = None
    create_new_memory_file: Optional[bool] = None
    memory_file_folder: Optional[str] = None
    memory_file_name: Optional[str] = None
    when_to_use: Optional[str] = None


# ---------------------------------------------------------------------------
# Semantic index (topics)
# ---------------------------------------------------------------------------


class TopicsResponse(BaseModel):
    """LLM response: topic keywords (array or wrapper). Accept list or object with topics key."""

    topics: List[str] = Field(default_factory=list, description="3-5 topic keywords")


# ---------------------------------------------------------------------------
# Information on Moi cleanup / synthesis
# ---------------------------------------------------------------------------


class RemoveIndicesResponse(BaseModel):
    """LLM response: indices of entries to remove."""

    remove: List[int] = Field(default_factory=list, description="Indices to remove")
    reasoning: Optional[str] = Field(None, description="Brief reason")


class PatternItem(BaseModel):
    """Single pattern in synthesis output."""

    statement: str = Field(default="", description="Pattern statement")
    affirmed: int = Field(default=0, description="Times affirmed")
    disproved: int = Field(default=0, description="Times disproved")
    slug: str = Field(default="pattern", description="Filename slug")
    supporting_dates: List[str] = Field(default_factory=list, description="Dates")


class PatternsSynthesisResponse(BaseModel):
    """LLM response: patterns from observations."""

    patterns: List[PatternItem] = Field(default_factory=list, description="Patterns")


# ---------------------------------------------------------------------------
# Behavior correction
# ---------------------------------------------------------------------------


class FindCausesResponse(BaseModel):
    """LLM response: candidate IDs that might cause unwanted behavior."""

    candidate_ids: List[str] = Field(default_factory=list, description="IDs to select")
    reasoning: Optional[str] = Field(None, description="Brief reasoning")


class EditAction(BaseModel):
    """Single edit: index and new text."""

    index: int = Field(..., description="1-based index")
    new_text: str = Field(default="", description="New bullet text")


class InterpretApplyResponse(BaseModel):
    """LLM response: remove indices and edits from user instruction."""

    remove: List[int] = Field(
        default_factory=list, description="1-based indices to remove"
    )
    edits: List[EditAction] = Field(default_factory=list, description="Edits to apply")


# ---------------------------------------------------------------------------
# Deduction user verification (conversation)
# ---------------------------------------------------------------------------


class QuestionResponse(BaseModel):
    """LLM response: clarification question."""

    question: Optional[str] = Field(None, description="Question to ask user")


class FollowupResponse(BaseModel):
    """LLM response: should conclude and optional follow-up question."""

    should_conclude: bool = Field(default=False, description="True if enough info")
    question: Optional[str] = Field(
        None, description="Follow-up question if not concluding"
    )
    reasoning: Optional[str] = Field(None, description="Brief explanation")


class ResolutionResponse(BaseModel):
    """LLM response: final resolution of verification conversation."""

    decision: Literal["confirmed", "modified", "discarded", "unclear"] = Field(
        ..., description="Resolution decision"
    )
    summary: Optional[str] = Field(None, description="Brief summary")
    final_deduction: Optional[str] = Field(None, description="Corrected deduction text")


# ---------------------------------------------------------------------------
# Daily digest (questions, health, follow-ups from diary)
# ---------------------------------------------------------------------------


class QuestionWithAnswer(BaseModel):
    """Single question with optional ELI5 answer."""

    question: str = Field(..., description="The question or curiosity")
    answer_eli5: Optional[str] = Field(
        None,
        description="ELI5 answer if model knows; null or 'I'm not sure – consider searching.' if not",
    )
    knows_answer: bool = Field(
        True,
        description="True if model provided a confident answer, False if unsure",
    )


class DailyDigestResponse(BaseModel):
    """LLM response: daily digest (Coach-Nanny-Aide) from diary entries."""

    research_assistant: Optional[str] = Field(
        None,
        description="Concise answers to informational/curiosity questions from the log; empty/null if no genuine questions.",
    )
    coach_review: str = Field(
        ...,
        description="The Coach's Review: The Win, The Insight, The Pattern. Synthesized text, not a list.",
    )
    nanny_checkin: Optional[str] = Field(
        None,
        description="Health/red-flag check-in; empty/null if nothing to report (e.g. user just tired).",
    )
    tomorrow_focus: List[str] = Field(
        default_factory=list,
        description="1-2 clear, low-friction nudges for tomorrow. Never suggest tasks already in completed_tasks.",
    )
