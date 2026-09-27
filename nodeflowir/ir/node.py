"""Configured node instances that appear inside a workflow."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, JsonValue, model_validator

from nodeflowir._model import NodeFlowModel
from nodeflowir.ir.types import Identifier, NodeTypeId, SemanticVersion


class BackoffStrategy(StrEnum):
    """Portable retry backoff strategies that a runtime may implement."""

    FIXED = "fixed"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


class RetryPolicy(NodeFlowModel):
    """Declarative retry intent; NodeFlowIR never performs the retry."""

    max_attempts: int = Field(ge=1, le=100)
    delay_seconds: float = Field(ge=0)
    backoff: BackoffStrategy = BackoffStrategy.FIXED
    max_delay_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check_max_delay(self) -> RetryPolicy:
        if self.max_delay_seconds is not None and self.max_delay_seconds < self.delay_seconds:
            raise ValueError("max_delay_seconds must be at least delay_seconds")
        return self


class TimeoutPolicy(NodeFlowModel):
    """A positive, runtime-enforced timeout expressed in seconds."""

    timeout_seconds: float = Field(gt=0)


class NodeInstance(NodeFlowModel):
    """One configured use of a registered node definition in a workflow.

    Input values are represented by workflow ``DataConnection`` records that
    target this node's ports.  ``config`` remains distinct from inputs because
    it is node-specific static configuration rather than data flow.
    """

    id: Identifier
    type: NodeTypeId
    type_version: SemanticVersion
    label: str | None = Field(default=None, min_length=1, max_length=200)
    config: dict[str, JsonValue] = Field(default_factory=dict)
    retry: RetryPolicy | None = None
    timeout: TimeoutPolicy | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
