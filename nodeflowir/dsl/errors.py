"""User-facing errors for the NodeFlow DSL pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceLocation:
    """A zero-dependency source location used by parser and compiler errors."""

    line: int
    column: int
    source_line: str | None = None


class NodeFlowDSLError(ValueError):
    """Base class for readable errors raised while handling NodeFlow DSL text."""

    def __init__(self, message: str, location: SourceLocation | None = None) -> None:
        self.message = message
        self.location = location
        if location is None:
            rendered = message
        elif location.source_line is None:
            rendered = f"Line {location.line}, column {location.column}: {message}"
        else:
            pointer = " " * max(location.column - 1, 0) + "^"
            rendered = (
                f"Line {location.line}, column {location.column}: {message}\n"
                f"{location.source_line}\n{pointer}"
            )
        super().__init__(rendered)


class DSLParseError(NodeFlowDSLError):
    """Raised when source text is not valid NodeFlow DSL syntax."""


class DSLCompileError(NodeFlowDSLError):
    """Raised when valid DSL syntax cannot map to the canonical IR."""


class DSLFormatError(NodeFlowDSLError):
    """Raised when an IR feature has no lossless DSL representation."""


class DSLValidationError(NodeFlowDSLError):
    """Raised when compiled IR fails the existing semantic validator."""

    def __init__(self, message: str, validation_result: object) -> None:
        self.validation_result = validation_result
        super().__init__(message)
