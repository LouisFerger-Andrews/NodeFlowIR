"""Catalog entries for capabilities already represented by the canonical IR."""

from __future__ import annotations

from nodeflowir.catalog.models import (
    BranchDefinition,
    CatalogConfigurationField,
    CatalogFieldType,
    CatalogItemKind,
    CatalogPort,
    CatalogPortKind,
    PortCardinality,
    PortDirection,
    WorkflowCatalogItem,
)
from nodeflowir.ir.types import TypeSpec, ValueKind

ANY = TypeSpec(kind=ValueKind.ANY)
BOOLEAN = TypeSpec(kind=ValueKind.BOOLEAN)
INTEGER = TypeSpec(kind=ValueKind.INTEGER)
NUMBER = TypeSpec(kind=ValueKind.NUMBER)
ARRAY = TypeSpec(kind=ValueKind.ARRAY)
OBJECT = TypeSpec(kind=ValueKind.OBJECT)
STRING = TypeSpec(kind=ValueKind.STRING)
DURATION = TypeSpec(kind=ValueKind.DURATION)


def _id(kind: CatalogItemKind, type_id: str) -> str:
    return f"{kind.value}:{type_id}"


def _control_input() -> CatalogPort:
    return CatalogPort(
        id="in",
        kind=CatalogPortKind.CONTROL,
        direction=PortDirection.INPUT,
    )


def _control_output(id: str, label: str | None = None, *, dynamic: bool = False) -> CatalogPort:
    return CatalogPort(
        id=id,
        label=label,
        kind=CatalogPortKind.CONTROL,
        direction=PortDirection.OUTPUT,
        cardinality=PortCardinality.MANY,
        required=False,
        dynamic=dynamic,
    )


def _data_input(
    id: str,
    data_type: TypeSpec = ANY,
    *,
    cardinality: PortCardinality = PortCardinality.ONE,
) -> CatalogPort:
    return CatalogPort(
        id=id,
        kind=CatalogPortKind.DATA,
        direction=PortDirection.INPUT,
        cardinality=cardinality,
        data_type=data_type,
    )


def _data_output(id: str, data_type: TypeSpec) -> CatalogPort:
    return CatalogPort(
        id=id,
        kind=CatalogPortKind.DATA,
        direction=PortDirection.OUTPUT,
        cardinality=PortCardinality.MANY,
        required=False,
        data_type=data_type,
    )


def _field(
    type: CatalogFieldType,
    *,
    required: bool = True,
    data_type: TypeSpec | None = None,
    **capabilities: str | bool,
) -> CatalogConfigurationField:
    return CatalogConfigurationField(
        type=type,
        required=required,
        data_type=data_type,
        capabilities=capabilities,
    )


def _item(
    kind: CatalogItemKind,
    type_id: str,
    display_name: str,
    category: str,
    *,
    description: str | None = None,
    config: dict[str, CatalogConfigurationField] | None = None,
    inputs: tuple[CatalogPort, ...] = (),
    outputs: tuple[CatalogPort, ...] = (),
    branch_definition: BranchDefinition | None = None,
    capabilities: dict[str, str | bool | int] | None = None,
) -> WorkflowCatalogItem:
    return WorkflowCatalogItem(
        id=_id(kind, type_id),
        kind=kind,
        type=type_id,
        display_name=display_name,
        description=description,
        category=category,
        configuration_schema=config or {},
        input_ports=inputs,
        output_ports=outputs,
        branch_definition=branch_definition,
        capabilities=capabilities or {},
    )


def builtin_catalog_items() -> tuple[WorkflowCatalogItem, ...]:
    """Return every currently supported built-in workflow capability.

    These entries describe existing IR models and operators only.  They do not
    turn expressions or control flow into executable application nodes.
    """

    expression = _field(
        CatalogFieldType.EXPRESSION,
        data_type=ANY,
        allowed_references=True,
        context_aware=True,
    )
    collection = _field(
        CatalogFieldType.COLLECTION_REFERENCE,
        data_type=ARRAY,
        allowed_references=True,
        earlier_nodes_only=True,
    )
    predicate = _field(
        CatalogFieldType.EXPRESSION,
        data_type=BOOLEAN,
        collection_item_scope=True,
    )
    item_scope = _field(
        CatalogFieldType.STRING,
        data_type=STRING,
        identifier=True,
        generated_identifier=True,
    )
    optional_item_scope = _field(
        CatalogFieldType.STRING,
        required=False,
        data_type=STRING,
        identifier=True,
        required_with="predicate",
    )
    optional_predicate = _field(
        CatalogFieldType.EXPRESSION,
        required=False,
        data_type=BOOLEAN,
        collection_item_scope=True,
        required_with="item_scope",
    )
    items: list[WorkflowCatalogItem] = [
        _item(
            CatalogItemKind.CONTROL_FLOW,
            "if",
            "If / Else",
            "Logic",
            config={"condition": expression},
            inputs=(_control_input(),),
            outputs=(_control_output("true", "True"), _control_output("false", "False")),
            capabilities={"else_if": True, "else": True},
        ),
        _item(
            CatalogItemKind.CONTROL_FLOW,
            "match",
            "Match",
            "Logic",
            config={"subject": expression},
            inputs=(_control_input(),),
            outputs=(
                _control_output("default", "Default"),
                _control_output("case", "Case", dynamic=True),
            ),
            branch_definition=BranchDefinition(
                dynamic=True,
                minimum_branches=1,
                branch_config_schema={
                    "case_value": _field(CatalogFieldType.LITERAL, data_type=ANY)
                },
                default_branch=True,
            ),
        ),
        _item(
            CatalogItemKind.CONTROL_FLOW,
            "foreach",
            "Foreach",
            "Logic",
            config={"collection": collection, "id": item_scope},
            inputs=(_control_input(),),
            outputs=(_control_output("each", "Each"), _control_output("completed", "Completed")),
        ),
        _item(
            CatalogItemKind.CONTROL_FLOW,
            "repeat",
            "Repeat",
            "Logic",
            config={"times": _field(CatalogFieldType.INTEGER, data_type=INTEGER)},
            inputs=(_control_input(),),
            outputs=(_control_output("body", "Body"), _control_output("completed", "Completed")),
            capabilities={"bounded": True, "minimum_times": 1},
        ),
        _item(
            CatalogItemKind.CONTROL_FLOW,
            "parallel",
            "Parallel",
            "Logic",
            config={
                "id": item_scope,
                "convergence": CatalogConfigurationField(
                    type=CatalogFieldType.ENUM,
                    enum_values=("all", "any"),
                    data_type=STRING,
                ),
            },
            inputs=(_control_input(),),
            outputs=(
                _control_output("branch", "Branch", dynamic=True),
                _control_output("completed", "Completed"),
            ),
            branch_definition=BranchDefinition(dynamic=True, minimum_branches=2),
            capabilities={"dynamic_output_ports": True, "minimum_branches": 2},
        ),
        _item(
            CatalogItemKind.CONTROL_FLOW,
            "break",
            "Break",
            "Logic",
            inputs=(_control_input(),),
            capabilities={"loop_only": True},
        ),
        _item(
            CatalogItemKind.CONTROL_FLOW,
            "continue",
            "Continue",
            "Logic",
            inputs=(_control_input(),),
            capabilities={"loop_only": True},
        ),
        _item(
            CatalogItemKind.CONTROL_FLOW,
            "error_flow",
            "Error Flow",
            "Logic",
            config={
                "categories": CatalogConfigurationField(
                    type=CatalogFieldType.ENUM,
                    required=False,
                    enum_values=("failed", "timeout", "cancelled"),
                    data_type=STRING,
                    capabilities={"multiple": True},
                )
            },
            inputs=(_control_input(),),
            outputs=(_control_output("handler", "Handler"),),
            capabilities={"attaches_to": "node_step"},
        ),
        _item(
            CatalogItemKind.EXECUTION_POLICY,
            "retry",
            "Retry",
            "Execution",
            config={
                "max_attempts": _field(CatalogFieldType.INTEGER, data_type=INTEGER),
                "delay_seconds": _field(
                    CatalogFieldType.DURATION, required=False, data_type=DURATION
                ),
                "backoff": CatalogConfigurationField(
                    type=CatalogFieldType.ENUM,
                    required=False,
                    enum_values=("fixed", "linear", "exponential"),
                    data_type=STRING,
                ),
                "max_delay_seconds": _field(
                    CatalogFieldType.DURATION, required=False, data_type=DURATION
                ),
            },
            capabilities={"attaches_to": "node_instance"},
        ),
        _item(
            CatalogItemKind.EXECUTION_POLICY,
            "timeout",
            "Timeout",
            "Execution",
            config={"timeout_seconds": _field(CatalogFieldType.DURATION, data_type=DURATION)},
            capabilities={"attaches_to": "node_instance"},
        ),
    ]

    binary_logic = (
        ("eq", "Equals"),
        ("ne", "Not Equal"),
        ("gt", "Greater Than"),
        ("lt", "Less Than"),
        ("gte", "Greater Than or Equal"),
        ("lte", "Less Than or Equal"),
        ("in", "In"),
        ("not_in", "Not In"),
    )
    for type_id, name in binary_logic:
        items.append(
            _item(
                CatalogItemKind.EXPRESSION,
                type_id,
                name,
                "Logic",
                inputs=(_data_input("left"), _data_input("right")),
                outputs=(_data_output("result", BOOLEAN),),
            )
        )
    items.append(
        _item(
            CatalogItemKind.EXPRESSION,
            "between",
            "Between",
            "Logic",
            inputs=(_data_input("value"), _data_input("lower"), _data_input("upper")),
            outputs=(_data_output("result", BOOLEAN),),
        )
    )
    for type_id, name in (
        ("and", "And"),
        ("or", "Or"),
        ("not", "Not"),
        ("exists", "Exists"),
        ("missing", "Missing"),
        ("is_null", "Is Null"),
        ("is_not_null", "Is Not Null"),
    ):
        items.append(
            _item(
                CatalogItemKind.EXPRESSION,
                type_id,
                name,
                "Logic",
                inputs=(_data_input("operand"),)
                if type_id in {"not", "exists", "missing", "is_null", "is_not_null"}
                else (_data_input("operands", cardinality=PortCardinality.MANY),),
                outputs=(_data_output("result", BOOLEAN),),
                capabilities={"variadic": type_id in {"and", "or"}},
            )
        )

    predicate_collection_config = {
        "collection": collection,
        "item_scope": item_scope,
        "predicate": predicate,
    }
    for type_id, name, result in (
        ("any", "Any", BOOLEAN),
        ("all", "All", BOOLEAN),
        ("none", "None", BOOLEAN),
        ("filter", "Filter", ARRAY),
    ):
        items.append(
            _item(
                CatalogItemKind.COLLECTION_OPERATION,
                type_id,
                name,
                "Collections",
                config=predicate_collection_config,
                inputs=(_data_input("collection", ARRAY),),
                outputs=(_data_output("result", result),),
                capabilities={"collection_item_scope": True},
            )
        )
    items.append(
        _item(
            CatalogItemKind.COLLECTION_OPERATION,
            "count",
            "Count",
            "Collections",
            config={
                "collection": collection,
                "item_scope": optional_item_scope,
                "predicate": optional_predicate,
            },
            inputs=(_data_input("collection", ARRAY),),
            outputs=(_data_output("result", INTEGER),),
            capabilities={"collection_item_scope": True, "predicate_optional": True},
        )
    )
    for type_id, name, result in (
        ("length", "Length", INTEGER),
        ("empty", "Empty", BOOLEAN),
        ("not_empty", "Not Empty", BOOLEAN),
        ("first", "First", ANY),
        ("last", "Last", ANY),
    ):
        items.append(
            _item(
                CatalogItemKind.COLLECTION_OPERATION,
                type_id,
                name,
                "Collections",
                config={"collection": collection},
                inputs=(_data_input("collection", ARRAY),),
                outputs=(_data_output("result", result),),
            )
        )

    transformation_specs = (
        ("map", "Map", {"collection": collection, "item_scope": item_scope, "mapper": expression}),
        (
            "select",
            "Select Fields",
            {"collection": collection, "fields": _field(CatalogFieldType.LIST, data_type=ARRAY)},
        ),
        (
            "pick",
            "Pick Fields",
            {"collection": collection, "fields": _field(CatalogFieldType.LIST, data_type=ARRAY)},
        ),
        (
            "omit",
            "Omit Fields",
            {"collection": collection, "fields": _field(CatalogFieldType.LIST, data_type=ARRAY)},
        ),
        (
            "rename",
            "Rename Fields",
            {"collection": collection, "rename": _field(CatalogFieldType.OBJECT, data_type=OBJECT)},
        ),
        ("distinct", "Distinct", {"collection": collection}),
        ("unique", "Unique", {"collection": collection}),
        ("flatten", "Flatten", {"collection": collection}),
        ("zip", "Zip", {"collection": collection, "other": collection}),
        (
            "join",
            "Join",
            {
                "left": collection,
                "right": collection,
                "left_scope": item_scope,
                "right_scope": item_scope,
                "predicate": predicate,
            },
        ),
        (
            "group_by",
            "Group By",
            {"collection": collection, "item_scope": item_scope, "mapper": expression},
        ),
        (
            "sort_by",
            "Sort By",
            {
                "collection": collection,
                "item_scope": item_scope,
                "mapper": expression,
                "direction": CatalogConfigurationField(
                    type=CatalogFieldType.ENUM,
                    required=False,
                    enum_values=("ascending", "descending"),
                    data_type=STRING,
                    has_default=True,
                    default="ascending",
                ),
            },
        ),
    )
    for type_id, name, config in transformation_specs:
        items.append(
            _item(
                CatalogItemKind.TRANSFORMATION,
                type_id,
                name,
                "Collections",
                config=config,
                inputs=(_data_input("collection", ARRAY),),
                outputs=(_data_output("result", ARRAY),),
                capabilities={
                    "collection_item_scope": type_id in {"map", "join", "group_by", "sort_by"}
                },
            )
        )
    for type_id, name in (
        ("merge", "Merge"),
        ("concat", "Concat"),
    ):
        items.append(
            _item(
                CatalogItemKind.TRANSFORMATION,
                type_id,
                name,
                "Collections",
                inputs=(_data_input("values", cardinality=PortCardinality.MANY),),
                outputs=(_data_output("result", ANY),),
                capabilities={"variadic": True, "minimum_values": 2},
            )
        )
    for type_id, name in (("append", "Append"), ("prepend", "Prepend")):
        items.append(
            _item(
                CatalogItemKind.TRANSFORMATION,
                type_id,
                name,
                "Collections",
                inputs=(_data_input("collection", ARRAY), _data_input("item")),
                outputs=(_data_output("result", ARRAY),),
            )
        )

    for type_id, name, result in (
        ("sum", "Sum", NUMBER),
        ("avg", "Average", NUMBER),
        ("min", "Minimum", ANY),
        ("max", "Maximum", ANY),
        ("count", "Count", INTEGER),
        ("distinct", "Distinct", ARRAY),
    ):
        items.append(
            _item(
                CatalogItemKind.AGGREGATION,
                type_id,
                name,
                "Aggregation",
                config={
                    "collection": collection,
                    "item_scope": optional_item_scope,
                    "predicate": optional_predicate,
                },
                inputs=(_data_input("collection", ARRAY),),
                outputs=(_data_output("result", result),),
            )
        )

    items.extend(
        [
            _item(
                CatalogItemKind.VALUE,
                "literal",
                "Literal",
                "Values",
                config={"value": _field(CatalogFieldType.LITERAL, data_type=ANY)},
                outputs=(_data_output("value", ANY),),
            ),
            _item(
                CatalogItemKind.VALUE,
                "coalesce",
                "Coalesce",
                "Values",
                inputs=(_data_input("values", ANY, cardinality=PortCardinality.MANY),),
                outputs=(_data_output("result", ANY),),
                capabilities={"variadic": True},
            ),
            _item(
                CatalogItemKind.VALUE,
                "default",
                "Default",
                "Values",
                inputs=(_data_input("value"), _data_input("fallback")),
                outputs=(_data_output("result", ANY),),
            ),
            _item(
                CatalogItemKind.VALUE,
                "object",
                "Object",
                "Values",
                config={"fields": _field(CatalogFieldType.OBJECT, data_type=OBJECT)},
                outputs=(_data_output("result", OBJECT),),
            ),
            _item(
                CatalogItemKind.VALUE,
                "array",
                "Array",
                "Values",
                config={"items": _field(CatalogFieldType.LIST, data_type=ARRAY)},
                outputs=(_data_output("result", ARRAY),),
            ),
            _item(
                CatalogItemKind.VALUE,
                "reference",
                "Reference",
                "References",
                config={
                    "source": _field(
                        CatalogFieldType.REFERENCE,
                        data_type=ANY,
                        allowed_references=True,
                        earlier_nodes_only=True,
                    )
                },
                outputs=(_data_output("value", ANY),),
            ),
            _item(
                CatalogItemKind.VALUE,
                "workflow_input_reference",
                "Workflow Input Reference",
                "References",
                config={
                    "source": _field(
                        CatalogFieldType.REFERENCE,
                        data_type=ANY,
                        reference_kind="workflow_input",
                    )
                },
                outputs=(_data_output("value", ANY),),
            ),
            _item(
                CatalogItemKind.VALUE,
                "node_output_reference",
                "Node Output Reference",
                "References",
                config={
                    "source": _field(
                        CatalogFieldType.NODE_OUTPUT_REFERENCE,
                        data_type=ANY,
                        allowed_references=True,
                        earlier_nodes_only=True,
                    )
                },
                outputs=(_data_output("value", ANY),),
            ),
            _item(
                CatalogItemKind.VALUE,
                "collection_reference",
                "Collection Reference",
                "References",
                config={"source": collection},
                outputs=(_data_output("value", ARRAY),),
            ),
            _item(
                CatalogItemKind.VALUE,
                "field_reference",
                "Field Reference",
                "References",
                config={
                    "source": _field(
                        CatalogFieldType.FIELD_REFERENCE, data_type=ANY, allowed_references=True
                    )
                },
                outputs=(_data_output("value", ANY),),
            ),
            _item(
                CatalogItemKind.VALUE,
                "constant_reference",
                "Constant Reference",
                "References",
                config={
                    "source": _field(
                        CatalogFieldType.REFERENCE,
                        data_type=ANY,
                        reference_kind="constant",
                    )
                },
                outputs=(_data_output("value", ANY),),
            ),
            _item(
                CatalogItemKind.VALUE,
                "loop_item_reference",
                "Loop Item Reference",
                "References",
                config={
                    "source": _field(
                        CatalogFieldType.FIELD_REFERENCE,
                        data_type=ANY,
                        reference_kind="loop_item",
                        loop_scope_only=True,
                    )
                },
                outputs=(_data_output("value", ANY),),
            ),
            _item(
                CatalogItemKind.VALUE,
                "convert",
                "Convert Type",
                "Values",
                config={
                    "value": _field(CatalogFieldType.REFERENCE, data_type=ANY),
                    "target_type": _field(CatalogFieldType.TYPE_SPEC, data_type=OBJECT),
                },
                inputs=(_data_input("value"),),
                outputs=(_data_output("result", ANY),),
            ),
        ]
    )
    for type_id, name in (
        ("contains", "Contains"),
        ("starts_with", "Starts With"),
        ("ends_with", "Ends With"),
        ("matches", "Matches"),
    ):
        items.append(
            _item(
                CatalogItemKind.EXPRESSION,
                type_id,
                name,
                "Text",
                inputs=(_data_input("left", STRING), _data_input("right", STRING)),
                outputs=(_data_output("result", BOOLEAN),),
            )
        )
    for type_id, name in (("lower", "Lowercase"), ("upper", "Uppercase"), ("trim", "Trim")):
        items.append(
            _item(
                CatalogItemKind.TRANSFORMATION,
                type_id,
                name,
                "Text",
                inputs=(_data_input("value", STRING),),
                outputs=(_data_output("result", STRING),),
            )
        )
    for type_id, name in (
        ("add", "Add"),
        ("subtract", "Subtract"),
        ("multiply", "Multiply"),
        ("divide", "Divide"),
        ("modulo", "Modulo"),
    ):
        items.append(
            _item(
                CatalogItemKind.EXPRESSION,
                type_id,
                name,
                "Math",
                inputs=(_data_input("left", NUMBER), _data_input("right", NUMBER)),
                outputs=(_data_output("result", NUMBER),),
            )
        )
    for type_id, name in (
        ("before", "Before"),
        ("after", "After"),
        ("add_duration", "Add Duration"),
        ("subtract_duration", "Subtract Duration"),
    ):
        items.append(
            _item(
                CatalogItemKind.EXPRESSION,
                type_id,
                name,
                "Date & Time",
                inputs=(_data_input("left"), _data_input("right")),
                outputs=(
                    _data_output("result", BOOLEAN if type_id in {"before", "after"} else ANY),
                ),
            )
        )
    return tuple(items)
