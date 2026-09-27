"""Application-owned dynamic provider and execution-handler binding contracts."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, TypeAlias

from pydantic import Field, JsonValue, TypeAdapter

from nodeflowir._model import NodeFlowModel
from nodeflowir.ir.types import Identifier
from nodeflowir.nodes.fields import BindingId


class ProviderOption(NodeFlowModel):
    """One stable selectable value returned by an application provider."""

    value: str = Field(min_length=1, max_length=500)
    label: str = Field(min_length=1, max_length=500)
    description: str | None = None
    disabled: bool = False
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ProviderContext(NodeFlowModel):
    """Generic context passed by a backend while resolving dynamic options.

    The data is deliberately opaque to NodeFlowIR.  An application can pass
    tenancy, authorization, prior configuration, or other context without
    making those concepts part of the IR package.
    """

    workflow_id: Identifier | None = None
    node_id: Identifier | None = None
    data: dict[str, JsonValue] = Field(default_factory=dict)


ProviderResult: TypeAlias = Sequence[ProviderOption | Mapping[str, JsonValue]]
DynamicProvider: TypeAlias = Callable[[ProviderContext], ProviderResult | Awaitable[ProviderResult]]
ExecutionHandler: TypeAlias = Callable[..., Any]


class BindingRegistryError(LookupError):
    """Base error for dynamic-provider and handler registry operations."""


class DuplicateBindingError(BindingRegistryError):
    """Raised when an application registers the same binding reference twice."""


class UnknownBindingError(BindingRegistryError):
    """Raised when an application asks for an unregistered binding reference."""


_binding_id_adapter = TypeAdapter(BindingId)


def _binding_id(value: str) -> str:
    return _binding_id_adapter.validate_python(value)


class ProviderRegistry:
    """Explicit registry of application-owned dynamic option providers."""

    def __init__(self) -> None:
        self._providers: dict[str, DynamicProvider] = {}

    def register(
        self, provider_id: str, provider: DynamicProvider, *, replace: bool = False
    ) -> DynamicProvider:
        provider_id = _binding_id(provider_id)
        if provider_id in self._providers and not replace:
            raise DuplicateBindingError(f"provider '{provider_id}' is registered")
        self._providers[provider_id] = provider
        return provider

    def resolve(self, provider_id: str) -> DynamicProvider:
        provider_id = _binding_id(provider_id)
        try:
            return self._providers[provider_id]
        except KeyError as error:
            raise UnknownBindingError(f"provider '{provider_id}' is not registered") from error

    def identifiers(self) -> tuple[str, ...]:
        """List registered provider references in deterministic order."""

        return tuple(sorted(self._providers))

    async def options(
        self, provider_id: str, *, context: ProviderContext | None = None
    ) -> tuple[ProviderOption, ...]:
        """Resolve fresh options for a frontend-facing configuration request."""

        result = self.resolve(provider_id)(context or ProviderContext())
        if inspect.isawaitable(result):
            result = await result
        options = tuple(ProviderOption.model_validate(option) for option in result)
        values = [option.value for option in options]
        if len(values) != len(set(values)):
            raise BindingRegistryError(f"provider '{provider_id}' returned duplicate option values")
        return options


class ExecutionHandlerRegistry:
    """Map a declarative node handler reference to application-owned code.

    This registry only stores and resolves references.  It deliberately offers
    no execution method, leaving invocation, context, retries, and isolation
    to the consuming runtime.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, ExecutionHandler] = {}

    def register(
        self, handler_id: str, handler: ExecutionHandler, *, replace: bool = False
    ) -> ExecutionHandler:
        handler_id = _binding_id(handler_id)
        if handler_id in self._handlers and not replace:
            raise DuplicateBindingError(f"handler '{handler_id}' is registered")
        self._handlers[handler_id] = handler
        return handler

    def resolve(self, handler_id: str) -> ExecutionHandler:
        handler_id = _binding_id(handler_id)
        try:
            return self._handlers[handler_id]
        except KeyError as error:
            raise UnknownBindingError(f"handler '{handler_id}' is not registered") from error

    def identifiers(self) -> tuple[str, ...]:
        """List registered handler references in deterministic order."""

        return tuple(sorted(self._handlers))
