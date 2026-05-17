"""Configuration for the LLM streaming loop guard.

The loop guard wraps each chat model's streaming output and aborts the
stream when it detects the model is stuck in an infinite repetition loop
(common with small / local models such as Qwen-1.8B, Yi-Lite, MiniCPM).

Two layers of detection:

* Layer A — exact n-gram suffix repetition (catches "好的好的好的…").
* Layer B — clause-skeleton similarity repetition (catches templated
  variations like "今天是周一，明天是周二，三天后是周三…").

See :mod:`deerflow.models.loop_detector` for algorithm details.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    # Import only at type-check time so we do not pull in ``deerflow.models``
    # during ``deerflow.config`` initialization.  The runtime import lives
    # inside :meth:`LoopGuardConfig.to_detector_config` and only fires when
    # the factory actually constructs a chat model — at which point all
    # config modules have finished loading.
    from deerflow.models.loop_detector import LoopDetectorConfig


class LoopGuardConfig(BaseModel):
    """User-facing config for the LLM streaming loop guard.

    All thresholds map 1:1 to :class:`LoopDetectorConfig` fields but expose
    Pydantic validation and YAML loading.
    """

    enabled: bool = Field(
        default=True,
        description=(
            "Whether to wrap each chat model with the loop guard.  When "
            "disabled, models are returned unmodified and no per-stream "
            "detector is allocated."
        ),
    )

    max_tail_chars: int = Field(
        default=8000,
        ge=200,
        le=20000,
        description=(
            "Rolling window of recent characters analyzed by the detector. "
            "8000 chars ≈ 5000 tokens — large enough to hold 50 repetitions "
            "of a 160-char loop cycle, ensuring we never miss a true loop."
        ),
    )
    check_interval_chars: int = Field(
        default=200,
        ge=10,
        le=1000,
        description=(
            "Run detection every N newly-streamed characters.  200 is a "
            "balanced trade-off — frequent enough for early detection, "
            "cheap enough on CPU."
        ),
    )
    min_content_length: int = Field(
        default=2000,
        ge=20,
        le=10000,
        description=(
            "Skip detection until at least this many characters have been "
            "streamed.  2000 ≈ 1300 tokens — allows substantial output before "
            "checking, prioritizing zero false positives."
        ),
    )

    ngram_sizes: list[int] = Field(
        default_factory=lambda: [12, 24, 48],
        description=(
            "Suffix lengths inspected by Layer A.  n=6 is excluded because "
            "short n-grams like 'shared', 'global' repeat frequently in normal "
            "prose/paths and cause false positives.  Sizes must be >= 2."
        ),
    )
    max_ngram_repeats: int = Field(
        default=50,
        ge=2,
        le=200,
        description=(
            "Number of times an exact suffix must repeat in the tail window "
            "before Layer A flags a loop.  50 is very permissive — true "
            "infinite loops hit this quickly, normal prose won't."
        ),
    )

    clause_window: int = Field(
        default=48,
        ge=3,
        le=128,
        description="How many recent clauses Layer B inspects.  Larger windows catch multi-block rotation loops.",
    )
    max_clause_repeats: int = Field(
        default=6,
        ge=2,
        le=50,
        description=(
            "How many similar clauses must appear in the window before "
            "Layer B flags a templated-variation loop."
        ),
    )
    clause_similarity_threshold: float = Field(
        default=0.6,
        ge=0.1,
        le=1.0,
        description=(
            "Sørensen–Dice coefficient on character bigrams above which "
            "two clauses are considered structurally similar.  0.6 is stricter "
            "than 0.5, reducing false positives on naturally similar sentences."
        ),
    )
    clause_min_length: int = Field(
        default=3,
        ge=1,
        le=200,
        description="Ignore clauses shorter than this when checking patterns.",
    )
    clause_max_length: int = Field(
        default=80,
        ge=10,
        le=1000,
        description=(
            "Ignore clauses longer than this — long-form prose is unlikely "
            "to be templated repetition."
        ),
    )

    def to_detector_config(self) -> "LoopDetectorConfig":
        """Translate the user-facing config to the algorithm's internal config.

        Uses a lazy runtime import to avoid a circular ``deerflow.config`` →
        ``deerflow.models`` → ``deerflow.config`` chain during startup.
        """
        from deerflow.models.loop_detector import LoopDetectorConfig

        return LoopDetectorConfig(
            enabled=self.enabled,
            max_tail_chars=self.max_tail_chars,
            check_interval_chars=self.check_interval_chars,
            min_content_length=self.min_content_length,
            ngram_sizes=tuple(self.ngram_sizes),
            max_ngram_repeats=self.max_ngram_repeats,
            clause_window=self.clause_window,
            max_clause_repeats=self.max_clause_repeats,
            clause_similarity_threshold=self.clause_similarity_threshold,
            clause_min_length=self.clause_min_length,
            clause_max_length=self.clause_max_length,
        )


__all__ = ["LoopGuardConfig"]
