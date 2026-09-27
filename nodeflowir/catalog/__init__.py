"""Unified frontend-facing catalog contracts for workflow authoring tools."""

from nodeflowir.catalog.builder import build_workflow_catalog, node_catalog_item
from nodeflowir.catalog.builtins import builtin_catalog_items
from nodeflowir.catalog.models import (
    BranchDefinition,
    CatalogConfigurationField,
    CatalogFieldType,
    CatalogItemKind,
    CatalogPort,
    CatalogPortKind,
    PortCardinality,
    PortDirection,
    WorkflowCatalog,
    WorkflowCatalogItem,
    ports_are_compatible,
)

__all__ = [
    "BranchDefinition",
    "CatalogConfigurationField",
    "CatalogFieldType",
    "CatalogItemKind",
    "CatalogPort",
    "CatalogPortKind",
    "PortCardinality",
    "PortDirection",
    "WorkflowCatalog",
    "WorkflowCatalogItem",
    "build_workflow_catalog",
    "builtin_catalog_items",
    "node_catalog_item",
    "ports_are_compatible",
]
