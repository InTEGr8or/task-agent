from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class TokensAccuracy(str, Enum):
    """Whether token counts are measured, estimated, or unknown."""

    measured = "measured"
    estimated = "estimated"
    unknown = "unknown"


class SubtaskMetric(BaseModel):
    """
    Self-reported agent execution metrics for cost optimization.

    Agents report these fields when completing a task (MCP ``complete_task``
    or CLI ``ta done``). All new cost fields are optional so partial reports
    remain valid; legacy callers that only set start_time/model/provider keep
    working.
    """

    model_config = ConfigDict(frozen=True, use_enum_values=True)

    start_time: datetime = Field(
        description="The ISO 8601 timestamp when the subtask started."
    )
    model: str = Field(
        description="The name of the AI model used (e.g., 'gemini-2.0-flash', 'claude-opus-4')."
    )
    provider: str = Field(
        description="The model provider service (e.g., 'google', 'anthropic', 'openai', 'xai')."
    )
    end_time: Optional[datetime] = Field(
        default=None, description="The ISO 8601 timestamp when the subtask completed."
    )
    cost: float = Field(
        default=0.0, description="The estimated cost of the subtask execution in USD."
    )
    model_version: Optional[str] = Field(
        default=None,
        description="Provider version string or snapshot id when known "
        "(e.g. '20250514', '20241022').",
    )
    agent_harness: Optional[str] = Field(
        default=None,
        description="Agent harness / product that drove the work "
        "(e.g. 'claude-code', 'codex', 'cursor', 'grok', 'antigravity', 'adk-worker').",
    )
    input_tokens: Optional[int] = Field(
        default=None,
        ge=0,
        description="Tokens consumed on the way up (prompt / context / input).",
    )
    output_tokens: Optional[int] = Field(
        default=None,
        ge=0,
        description="Tokens produced on the way down (completion / output).",
    )
    tokens_accuracy: TokensAccuracy = Field(
        default=TokensAccuracy.unknown,
        description="Whether token counts are measured, estimated, or unknown.",
    )
    duration_seconds: Optional[float] = Field(
        default=None,
        ge=0,
        description="Wall-clock seconds spent on the task (preferred over deriving "
        "from start/end when the agent has a better clock).",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Free-form cost-relevant notes (cache hits, retries, tool loops, etc.).",
    )

    def effective_duration_seconds(self) -> Optional[float]:
        """Return duration_seconds, or derive from start/end when both present."""
        if self.duration_seconds is not None:
            return self.duration_seconds
        if self.end_time is not None:
            delta = self.end_time - self.start_time
            return max(0.0, delta.total_seconds())
        return None

    def total_tokens(self) -> Optional[int]:
        """Sum of input and output tokens when either is known."""
        if self.input_tokens is None and self.output_tokens is None:
            return None
        return (self.input_tokens or 0) + (self.output_tokens or 0)

    def to_meta_dict(self) -> dict[str, Any]:
        """Serialize for ``meta.json`` (JSON-friendly values only)."""
        data: dict[str, Any] = {
            "start_time": self.start_time.isoformat(),
            "model": self.model,
            "provider": self.provider,
            "cost_usd": self.cost,
            "tokens_accuracy": (
                self.tokens_accuracy.value
                if isinstance(self.tokens_accuracy, TokensAccuracy)
                else self.tokens_accuracy
            ),
        }
        if self.end_time is not None:
            data["end_time"] = self.end_time.isoformat()
        if self.model_version is not None:
            data["model_version"] = self.model_version
        if self.agent_harness is not None:
            data["agent_harness"] = self.agent_harness
        if self.input_tokens is not None:
            data["input_tokens"] = self.input_tokens
        if self.output_tokens is not None:
            data["output_tokens"] = self.output_tokens
        total = self.total_tokens()
        if total is not None:
            data["total_tokens"] = total
        duration = self.effective_duration_seconds()
        if duration is not None:
            data["duration_seconds"] = duration
        if self.notes:
            data["notes"] = self.notes
        return data

    def to_markdown(self) -> str:
        """Render a human-readable markdown section for the task README."""
        lines = ["## Agent Metrics", ""]
        lines.append(f"- **Model**: `{self.model}`")
        if self.model_version:
            lines.append(f"- **Model version**: `{self.model_version}`")
        lines.append(f"- **Provider**: `{self.provider}`")
        if self.agent_harness:
            lines.append(f"- **Agent harness**: `{self.agent_harness}`")
        duration = self.effective_duration_seconds()
        if duration is not None:
            lines.append(f"- **Duration**: {self._format_duration(duration)}")
        lines.append(f"- **Started**: {self.start_time.isoformat()}")
        if self.end_time is not None:
            lines.append(f"- **Ended**: {self.end_time.isoformat()}")
        if self.input_tokens is not None or self.output_tokens is not None:
            accuracy = (
                self.tokens_accuracy.value
                if isinstance(self.tokens_accuracy, TokensAccuracy)
                else self.tokens_accuracy
            )
            inn = self.input_tokens if self.input_tokens is not None else "—"
            out = self.output_tokens if self.output_tokens is not None else "—"
            total = self.total_tokens()
            total_s = str(total) if total is not None else "—"
            lines.append(
                f"- **Tokens**: in={inn}, out={out}, total={total_s} ({accuracy})"
            )
        if self.cost:
            lines.append(f"- **Cost (USD)**: {self.cost:.6f}")
        if self.notes:
            lines.append(f"- **Notes**: {self.notes}")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        seconds = int(round(seconds))
        hours, rem = divmod(seconds, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours}h {minutes}m {secs}s ({seconds}s)"
        if minutes:
            return f"{minutes}m {secs}s ({seconds}s)"
        return f"{secs}s"

    @classmethod
    def from_completion_args(
        cls,
        *,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        model_version: Optional[str] = None,
        agent_harness: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        tokens_accuracy: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        cost_usd: Optional[float] = None,
        started_at: Optional[str] = None,
        ended_at: Optional[str] = None,
        notes: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> Optional["SubtaskMetric"]:
        """Build a metric from optional completion-tool fields.

        Returns ``None`` when no cost-relevant field was supplied so callers can
        skip writing empty metrics.
        """
        has_signal = any(
            v is not None
            for v in (
                model,
                provider,
                model_version,
                agent_harness,
                input_tokens,
                output_tokens,
                duration_seconds,
                cost_usd,
                started_at,
                ended_at,
                notes,
            )
        )
        # tokens_accuracy alone (defaulting to unknown) is not enough signal
        if (
            tokens_accuracy is not None
            and tokens_accuracy != TokensAccuracy.unknown.value
        ):
            has_signal = True
        if not has_signal:
            return None

        clock = now or datetime.now().astimezone()
        end_dt = cls._parse_dt(ended_at) if ended_at else clock
        if started_at:
            start_dt = cls._parse_dt(started_at)
        elif duration_seconds is not None:
            from datetime import timedelta

            start_dt = end_dt - timedelta(seconds=float(duration_seconds))
        else:
            start_dt = end_dt

        accuracy = TokensAccuracy.unknown
        if tokens_accuracy:
            try:
                accuracy = TokensAccuracy(tokens_accuracy.lower())
            except ValueError as e:
                raise ValueError(
                    f"tokens_accuracy must be one of "
                    f"{[a.value for a in TokensAccuracy]}, got {tokens_accuracy!r}"
                ) from e

        return cls(
            start_time=start_dt,
            end_time=end_dt,
            model=model or "unknown",
            provider=provider or "unknown",
            model_version=model_version,
            agent_harness=agent_harness,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens_accuracy=accuracy,
            duration_seconds=duration_seconds,
            cost=float(cost_usd) if cost_usd is not None else 0.0,
            notes=notes,
        )

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
