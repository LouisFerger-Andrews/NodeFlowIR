"""Shared Pydantic defaults for public NodeFlowIR models."""

from pydantic import BaseModel, ConfigDict


class NodeFlowModel(BaseModel):
    """Base model that keeps IR documents explicit and safe to evolve."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
