from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, model_validator


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class QCIntentRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["black_segment", "frozen_scene", "audio_silence"]
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    reason: str = Field(min_length=3, max_length=300)

    @model_validator(mode="after")
    def validate_range(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("QC intent end_seconds must be greater than start_seconds")
        return self


class TimelineClip(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    asset_id: UUID
    track_id: str
    timeline_start: float = Field(ge=0)
    source_in: float = Field(ge=0)
    source_out: float = Field(gt=0)
    transform: dict[str, Any] = Field(default_factory=dict)
    audio_gain_db: float = 0
    story_beat_id: UUID | None = None
    rationale: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class TimelineDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "0.1"
    project_id: UUID
    version: int = Field(default=0, ge=0)
    sequence: dict[str, Any] = Field(default_factory=dict)
    clips: list[TimelineClip] = Field(default_factory=list)
    editorial_notes: list[str] = Field(default_factory=list)
    qc_intent: list[QCIntentRange] = Field(default_factory=list, max_length=100)


class SaveTimelineRequest(BaseModel):
    timeline: TimelineDocument
    expected_version: int | None = Field(default=None, ge=0)
    message: str | None = None
    idempotency_key: str | None = None


class RestoreRequest(BaseModel):
    expected_version: int = Field(ge=0)
    message: str | None = None


class CreateRenderRequest(BaseModel):
    timeline_version: int | None = Field(default=None, ge=1)
    render_profile: dict[str, Any] = Field(default_factory=dict)
    request_key: str | None = Field(default=None, max_length=128)


class QCCriticApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_ids: list[str] = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)
