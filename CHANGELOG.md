# Changelog

All notable changes to NodeFlowIR are documented here.

## 0.1.0 — Initial application-integration baseline

- Canonical, schema-versioned Pydantic workflow IR with deterministic expressions, transformations, control flow, serialization, validation, structural limits, fingerprints, and revision diffs.
- Versioned Node SDK, configuration contracts, dynamic provider references, execution-handler references, and instance-local registries.
- Unified catalog, frontend presentation contract, typed ports, and configuration metadata for visual builders.
- Optional NodeFlow DSL that compiles to the canonical IR and deterministic formatting for the supported subset.
- Shared authoring context for structured AI authoring using the canonical schema, catalog, and explicitly supplied provider values.
- Portable ownership, revision, sharing intent, execution-identity, and protected resource-dependency contracts.
- Thin `NodeFlow` consumer facade that composes registration, catalog, validation, DSL, authoring, compatibility, and non-executing handler resolution.

NodeFlowIR does not provide workflow execution, scheduling, persistence, authentication, authorization enforcement, provider/handler business implementations, frontend components, or infrastructure integrations.
