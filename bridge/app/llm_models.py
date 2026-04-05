from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field
from pydantic_extension.model_slicing import LLMField, ModeSlicingMixin
from pydantic_extension.model_slicing.mixin import ExcludeMode


class LlmApprovalDecisionContext(ModeSlicingMixin, BaseModel):
    """LLM-safe approval prompt context.

    Only the `llm` slice is intended for prompt construction.
    """

    approval_kind: Annotated[str, LLMField()] = Field(...)
    approval_id: Annotated[str, LLMField()] = Field(...)
    tool_name: Annotated[str, LLMField()] = Field(...)
    command: Annotated[str | None, LLMField()] = Field(default=None)
    summary: Annotated[str | None, LLMField()] = Field(default=None)

    prompt_purpose: Annotated[str, ExcludeMode("llm")] = Field(
        default="local_governance_approval"
    )
