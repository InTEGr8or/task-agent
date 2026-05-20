from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class SubtaskMetric(BaseModel):
    """
    Data model for tracking subtask execution metrics.
    """

    model_config = ConfigDict(frozen=True)

    start_time: datetime = Field(
        description="The ISO 8601 timestamp when the subtask started."
    )
    model: str = Field(
        description="The name of the AI model used (e.g., 'gemini-2.0-flash')."
    )
    provider: str = Field(
        description="The model provider service (e.g., 'google', 'anthropic', 'openai')."
    )
    end_time: Optional[datetime] = Field(
        default=None, description="The ISO 8601 timestamp when the subtask completed."
    )
    cost: float = Field(
        default=0.0, description="The estimated cost of the subtask execution in USD."
    )
