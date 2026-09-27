"""Thin, explicit integration facade for consuming NodeFlowIR applications."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from typing import TypeAlias

from pydantic import JsonValue

from nodeflowir.authoring import (
    AuthoringContext,
    ProviderValuesInput,
    build_authoring_context,
    validate_authored_workflow,
)
from nodeflowir.catalog import WorkflowCatalog, build_workflow_catalog
from nodeflowir.compatibility import CompatibilityResult, check_workflow_compatibility
from nodeflowir.dsl import compile_dsl, format_workflow
from nodeflowir.governance import ResourceDependency, collect_resource_dependencies
from nodeflowir.ir import NodeInstance, Workflow
from nodeflowir.nodes import (
    ExecutionHandlerRegistry,
    NodeDefinition,
    NodeRegistry,
    ProviderContext,
    ProviderOption,
    ProviderRegistry,
    UnknownBindingError,
)
from nodeflowir.nodes.bindings import DynamicProvider, ExecutionHandler
from nodeflowir.serialization import (
    MigrationRegistry,
    WorkflowDiff,
    workflow_diff,
    workflow_fingerprint,
    workflow_from_document,
    workflow_from_json,
)
from nodeflowir.validation import ValidationResult, validate_workflow

WorkflowPayload: TypeAlias = Workflow | str | bytes | bytearray | Mapping[str, JsonValue]
NodeDeclaration: TypeAlias = NodeDefinition | type[object] | Callable[..., object]


class WorkflowValidationError(ValueError):
    """Raised when a parsed canonical workflow has semantic diagnostics."""

    def __init__(self, result: ValidationResult) -> None:
        self.result = result
        super().__init__(
            "workflow validation failed: " + "; ".join(issue.message for issue in result.issues)
        )


class NodeHandlerResolutionError(LookupError):
    """Raised when a node instance has no resolvable application handler binding."""

    def __init__(self, node: NodeInstance, message: str, *, handler_id: str | None = None) -> None:
        self.node_instance_id = node.id
        self.node_type = node.type
        self.node_version = node.type_version
        self.handler_id = handler_id
        super().__init__(message)


class NodeFlow:
    """Compose existing NodeFlowIR contracts into one application-local facade.

    The facade owns no global state and does not execute a workflow, a node
    handler, or a provider without an explicit caller request.  It simply
    coordinates registration, canonical parsing, validation, discovery, and
    handoff to an application-owned runtime.
    """

    def __init__(
        self,
        *,
        nodes: NodeRegistry | None = None,
        providers: ProviderRegistry | None = None,
        handlers: ExecutionHandlerRegistry | None = None,
        migrations: MigrationRegistry | None = None,
    ) -> None:
        self.nodes = nodes if nodes is not None else NodeRegistry()
        self.providers = providers if providers is not None else ProviderRegistry()
        self.handlers = handlers if handlers is not None else ExecutionHandlerRegistry()
        self.migrations = migrations if migrations is not None else MigrationRegistry()

    def register_node(
        self, declaration: NodeDeclaration, *, replace: bool = False
    ) -> NodeDefinition:
        """Register a definition or a class/function already decorated with ``@node``."""

        definition = (
            declaration
            if isinstance(declaration, NodeDefinition)
            else getattr(declaration, "__nodeflowir_definition__", None)
        )
        if not isinstance(definition, NodeDefinition):
            raise TypeError(
                "register_node requires a NodeDefinition or a class/function decorated with @node"
            )
        return self.nodes.register(definition, replace=replace)

    def register_provider(
        self, provider_id: str, provider: DynamicProvider, *, replace: bool = False
    ) -> DynamicProvider:
        """Register an application-owned dynamic option provider."""

        return self.providers.register(provider_id, provider, replace=replace)

    def register_handler(
        self, handler_id: str, handler: ExecutionHandler, *, replace: bool = False
    ) -> ExecutionHandler:
        """Register application code without calling it."""

        return self.handlers.register(handler_id, handler, replace=replace)

    @property
    def catalog(self) -> WorkflowCatalog:
        """Return current discovery metadata; registrations are never cached globally."""

        return self.build_catalog()

    def build_catalog(self) -> WorkflowCatalog:
        """Build the shared frontend and AI workflow catalog."""

        return build_workflow_catalog(node_registry=self.nodes)

    async def resolve_provider(
        self, provider_id: str, *, context: ProviderContext | None = None
    ) -> tuple[ProviderOption, ...]:
        """Resolve one explicitly requested application provider."""

        return await self.providers.options(provider_id, context=context)

    def validate(self, workflow: Workflow) -> ValidationResult:
        """Apply the established non-executing canonical workflow validator."""

        return validate_workflow(workflow, self.nodes)

    def load_workflow(self, payload: WorkflowPayload) -> Workflow:
        """Parse, migrate when explicitly supported, and validate canonical workflow data.

        JSON/Pydantic parsing errors retain their native structured exceptions.
        Semantic failures raise :class:`WorkflowValidationError`, whose
        ``result`` is the normal structured ``ValidationResult``.
        """

        if isinstance(payload, Workflow):
            workflow = payload
        elif isinstance(payload, Mapping):
            workflow = workflow_from_document(payload, migrations=self.migrations)
        else:
            workflow = workflow_from_json(payload, migrations=self.migrations)
        result = self.validate(workflow)
        if not result.is_valid:
            raise WorkflowValidationError(result)
        return workflow

    def import_workflow(self, payload: WorkflowPayload) -> Workflow:
        """Alias the normal schema-aware load and validation entry point."""

        return self.load_workflow(payload)

    def export_workflow(self, workflow: Workflow) -> dict[str, JsonValue]:
        """Return the canonical JSON-compatible document for application storage or APIs."""

        return workflow.model_dump(mode="json")

    def check_compatibility(
        self, payload: WorkflowPayload, *, catalog_version: str | None = None
    ) -> CompatibilityResult:
        """Discover schema/node/catalog support before normal parsing and validation."""

        return check_workflow_compatibility(
            payload,
            registry=self.nodes,
            migrations=self.migrations,
            catalog_version=catalog_version,
        )

    def workflow_fingerprint(self, workflow: Workflow) -> str:
        """Fingerprint deterministic workflow semantics without external state."""

        return workflow_fingerprint(workflow)

    def diff_workflows(self, before: Workflow, after: Workflow) -> WorkflowDiff:
        """Return a structured, read-only comparison of two workflow revisions."""

        return workflow_diff(before, after)

    def parse_dsl(self, source: str) -> Workflow:
        """Compile DSL source to the same validated canonical ``Workflow`` model."""

        return compile_dsl(source, self.nodes)

    def format_dsl(self, workflow: Workflow) -> str:
        """Format a supported canonical workflow without changing its semantics."""

        return format_workflow(workflow)

    def build_authoring_context(
        self,
        *,
        provider_values: ProviderValuesInput | None = None,
        categories: Collection[str] | None = None,
        item_ids: Collection[str] | None = None,
    ) -> AuthoringContext:
        """Build shared visual/AI capability context without resolving providers."""

        return build_authoring_context(
            catalog=self.build_catalog(),
            provider_values=provider_values,
            categories=categories,
            item_ids=item_ids,
        )

    def validate_authored_workflow(
        self,
        workflow: Workflow,
        *,
        authoring_context: AuthoringContext | None = None,
        provider_values: ProviderValuesInput | None = None,
    ) -> ValidationResult:
        """Apply canonical validation plus optional explicitly supplied option checks."""

        return validate_authored_workflow(
            workflow,
            registry=self.nodes,
            context=authoring_context,
            provider_values=provider_values,
        )

    def resolve_handler(self, node: NodeInstance) -> ExecutionHandler:
        """Resolve, but never invoke, the application handler for a node instance."""

        definition = self.nodes.resolve(node.type, node.type_version)
        if definition.handler is None:
            raise NodeHandlerResolutionError(
                node,
                f"node '{node.id}' ({node.type}@{node.type_version}) has no handler reference",
            )
        try:
            return self.handlers.resolve(definition.handler)
        except UnknownBindingError as error:
            raise NodeHandlerResolutionError(
                node,
                (
                    f"node '{node.id}' ({node.type}@{node.type_version}) requires unregistered "
                    f"handler '{definition.handler}'"
                ),
                handler_id=definition.handler,
            ) from error

    def collect_resource_dependencies(self, workflow: Workflow) -> tuple[ResourceDependency, ...]:
        """Inspect declared protected resources without resolving or authorizing them."""

        return collect_resource_dependencies(workflow, self.nodes)
