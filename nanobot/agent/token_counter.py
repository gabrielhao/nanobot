"""Token counting and context window management."""

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TokenMetrics:
    """Track token usage per session."""

    session_key: str
    estimated_input_tokens: int = 0
    actual_output_tokens: int = 0
    total_requests: int = 0
    created_at: str = ""
    last_request_at: str = ""


class TokenCounter:
    """Estimate and track token usage. Uses hardcoded ratios for major models."""

    # Token estimation ratios (chars -> tokens). Vary by model; these are conservative.
    TOKEN_RATIOS = {
        "claude-3-5-sonnet": 3.5,  # Actual: varies, ~0.35 tokens/char
        "claude": 3.5,
        "gpt-4": 4.0,
        "gpt-3.5": 4.5,
        "text-davinci": 4.0,
        "default": 4.0,  # Default: ~1 token per 4 chars
    }

    # Context window sizes (in tokens)
    CONTEXT_LIMITS = {
        "claude-3-5-sonnet": 200_000,
        "claude-opus": 200_000,
        "gpt-4-turbo": 128_000,
        "gpt-4": 8_000,
        "gpt-3.5-turbo": 4_096,
        "default": 128_000,
    }

    @classmethod
    def estimate_tokens(cls, text: str, model: str = "default") -> int:
        """Estimate token count for text (fast, not 100% accurate)."""
        ratio = cls._get_ratio(model)
        # Rough formula: tokens ≈ chars / 4 (varies by model, content type)
        return max(1, int(len(text) / ratio))

    @classmethod
    def estimate_messages_tokens(cls, messages: list[dict], model: str = "default") -> int:
        """Estimate total tokens for message list."""
        total = 0
        for msg in messages:
            # Role overhead: ~4 tokens per message
            total += 4

            # Content
            if isinstance(msg.get("content"), str):
                total += cls.estimate_tokens(msg["content"], model)
            elif isinstance(msg.get("content"), list):
                # Handle vision messages
                for item in msg["content"]:
                    if isinstance(item, dict) and item.get("type") == "text":
                        total += cls.estimate_tokens(item.get("text", ""), model)
                    elif isinstance(item, dict) and item.get("type") == "image_url":
                        # Image tokens vary by resolution; estimate ~300-1000 tokens
                        total += 500

            # Tool calls and results
            if "tool_calls" in msg:
                total += cls.estimate_tokens(str(msg["tool_calls"]), model)
            if "tool_call_id" in msg or msg.get("role") == "tool":
                total += cls.estimate_tokens(msg.get("content", ""), model)

        return total

    @classmethod
    def get_context_limit(cls, model: str) -> int:
        """Get context window size for model."""
        for key, limit in cls.CONTEXT_LIMITS.items():
            if key in model:
                return limit
        return cls.CONTEXT_LIMITS["default"]

    @classmethod
    def _get_ratio(cls, model: str) -> float:
        """Get token estimation ratio for model."""
        for key, ratio in cls.TOKEN_RATIOS.items():
            if key in model:
                return ratio
        return cls.TOKEN_RATIOS["default"]

    @classmethod
    def should_consolidate(
        cls,
        messages: list[dict],
        model: str,
        message_threshold: int = 100,
        token_threshold_percent: float = 0.75,
    ) -> tuple[bool, dict[str, Any]]:
        """
        Determine if consolidation is needed.

        Args:
            messages: Current message list
            model: Model name
            message_threshold: Consolidate if this many unconsolidated messages
            token_threshold_percent: Consolidate if context exceeds this % of limit

        Returns:
            (should_consolidate, metrics_dict)
        """
        estimated_tokens = cls.estimate_messages_tokens(messages, model)
        context_limit = cls.get_context_limit(model)
        token_ratio = estimated_tokens / context_limit

        should_consolidate = (
            len(messages) >= message_threshold
            or token_ratio >= token_threshold_percent
        )

        metrics = {
            "estimated_input_tokens": estimated_tokens,
            "context_limit": context_limit,
            "utilization_percent": int(token_ratio * 100),
            "should_consolidate": should_consolidate,
            "reason": (
                "message_count" if len(messages) >= message_threshold
                else "token_ratio" if token_ratio >= token_threshold_percent
                else "none"
            ),
        }

        return should_consolidate, metrics


class ContextWindowMonitor:
    """Track token usage per session and alert on context bloat."""

    def __init__(self, max_history_size: int = 100):
        self.metrics: dict[str, TokenMetrics] = {}
        self.history: dict[str, deque] = {}
        self.max_history_size = max_history_size

    def record_request(
        self,
        session_key: str,
        input_tokens: int,
        output_tokens: int,
        timestamp: str,
    ) -> None:
        """Record a request's token usage."""
        if session_key not in self.metrics:
            self.metrics[session_key] = TokenMetrics(session_key=session_key)
            self.history[session_key] = deque(maxlen=self.max_history_size)

        m = self.metrics[session_key]
        m.estimated_input_tokens = input_tokens
        m.actual_output_tokens = output_tokens
        m.total_requests += 1
        m.last_request_at = timestamp

        self.history[session_key].append({"input": input_tokens, "output": output_tokens})

    def get_average_tokens(self, session_key: str) -> dict[str, float]:
        """Get average token usage for session."""
        if session_key not in self.history or not self.history[session_key]:
            return {"avg_input": 0, "avg_output": 0}

        hist = list(self.history[session_key])
        avg_input = sum(h["input"] for h in hist) / len(hist)
        avg_output = sum(h["output"] for h in hist) / len(hist)

        return {"avg_input": avg_input, "avg_output": avg_output}

    def get_efficiency_score(self, session_key: str) -> float:
        """
        Score session efficiency (0-100).

        Lower = wasting tokens. <50 = bloated context.
        """
        if not self.history[session_key]:
            return 100.0

        hist = list(self.history[session_key])
        avg_input = sum(h["input"] for h in hist) / len(hist)

        # Ideal: input tokens / output tokens ~= 1:1
        # If input dominates, context is bloated
        if hist[-1]["output"] == 0:
            return 0.0

        ratio = hist[-1]["input"] / hist[-1]["output"]
        # Score decays as ratio increases (ideal: ~1.0)
        score = min(100, max(0, 100 * (2.0 - ratio)))
        return score
