from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict

class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)

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
