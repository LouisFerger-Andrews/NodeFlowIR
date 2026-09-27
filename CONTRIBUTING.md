# Contributing

NodeFlowIR is an application-independent library. Changes must preserve the boundary that it defines workflow semantics and contracts while consuming applications own execution, identity, authorization, persistence, scheduling, and infrastructure.

## Development

Use the reproducible Nix shell, then install the project development dependencies:

```bash
nix develop
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

Before opening a pull request, also run `python -m compileall -q nodeflowir` and build the package with `uv run python -m build`.

## Contract changes

Changes to canonical IR models, serialization, the DSL, catalog/presentation metadata, governance models, or the public API require focused tests and compatibility review. Keep polymorphic models explicit and Pydantic-friendly. Do not add application-specific nodes, runtime execution, persistence, or infrastructure integrations to this repository.

Run the full suite after changes. Tests should verify semantic behavior and public API imports, not only internal implementation details.
