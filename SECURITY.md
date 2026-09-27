# Security policy

NodeFlowIR processes declarative workflow definitions. It deliberately does not execute nodes, invoke handlers, resolve live providers automatically, or manage credentials. Consuming applications remain responsible for execution isolation, identity, authorization, resource access, and infrastructure security.

## Reporting a vulnerability

Please do not disclose sensitive vulnerabilities in a public GitHub issue. Use GitHub private vulnerability reporting for this repository when it is available. If private reporting is unavailable, contact the repository owner through GitHub and request a confidential reporting channel before sharing technical details.

Include the affected version or commit, a concise impact assessment, reproduction steps, and any proposed mitigation. Do not include real credentials, private workflow data, or production resource identifiers.

## Scope notes

Node definition regular-expression constraints are application-authored contracts and are validated with Python's standard `re` module when static configuration is checked. Applications should treat patterns as trusted definition metadata, or independently constrain/review them before registration. NodeFlowIR does not accept executable code through workflows or its DSL.
