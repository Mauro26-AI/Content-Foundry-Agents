"""
Pydantic request/response models for the FastAPI HITL backend.
"""

from pydantic import BaseModel, Field


# Outbound DTOs

class PickDTO(BaseModel):
    id: int
    headline: str
    summary: str
    relevance: str
    source_urls: list[str] = Field(default_factory=list)


class TokenUsageDTO(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class RunStateDTO(BaseModel):
    """Public snapshot of a run, returned by most endpoints."""

    thread_id: str
    phase: str = Field(
        description=(
            "One of 'awaiting_pick', 'awaiting_approval', 'finalized', "
            "'discarded'. Drives client UI."
        )
    )
    picks: list[PickDTO] = Field(default_factory=list)
    selected_pick_id: int | None = None
    draft_post: str = ""
    saved_path: str | None = None
    token_usage: TokenUsageDTO = Field(default_factory=TokenUsageDTO)



# Inbound DTOs

class RunInput(BaseModel):
    max_editorial_picks: int = Field(
        default=5,
        ge=1,
        le=10,
        description="How many editorial picks the Strategist should return (1-10).",
    )


class PickInput(BaseModel):
    pick_id: int = Field(ge=1, description="ID of the editorial pick to develop.")


class RegenerateInput(BaseModel):
    feedback: str = Field(
        default="",
        description="Optional free-text guidance for the rewrite.",
    )
