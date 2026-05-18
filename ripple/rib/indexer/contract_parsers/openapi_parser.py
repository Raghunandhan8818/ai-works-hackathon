from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ripple.rib.graph.schema import Constraint, FieldNode, TransportKind


def parse_openapi(
    spec_path: str | Path,
    producer_service: str,
) -> list[FieldNode]:
    path = Path(spec_path)
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        return []

    paths = raw.get("paths") or {}
    components = raw.get("components") or {}
    schemas = components.get("schemas") or {}

    fields: list[FieldNode] = []
    for route, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method.startswith("x-") or not isinstance(operation, dict):
                continue
            endpoint = f"{method.upper()} {route}"
            fields.extend(
                _extract_from_operation(
                    operation=operation,
                    endpoint=endpoint,
                    producer_service=producer_service,
                    schemas=schemas,
                    spec_path=str(path),
                )
            )
    return fields


def _extract_from_operation(
    operation: dict[str, Any],
    endpoint: str,
    producer_service: str,
    schemas: dict[str, Any],
    spec_path: str,
) -> list[FieldNode]:
    fields: list[FieldNode] = []
    for location in ("requestBody", "responses"):
        block = operation.get(location)
        if not isinstance(block, dict):
            continue
        if location == "requestBody":
            content = block.get("content") or {}
            for _, media in content.items():
                if isinstance(media, dict):
                    schema = media.get("schema")
                    fields.extend(
                        _walk_schema(
                            schema=schema,
                            prefix="request",
                            endpoint=endpoint,
                            producer_service=producer_service,
                            schemas=schemas,
                            spec_path=spec_path,
                        )
                    )
        else:
            for status, response in block.items():
                if not isinstance(response, dict):
                    continue
                content = response.get("content") or {}
                for _, media in content.items():
                    if isinstance(media, dict):
                        schema = media.get("schema")
                        fields.extend(
                            _walk_schema(
                                schema=schema,
                                prefix=f"response.{status}",
                                endpoint=endpoint,
                                producer_service=producer_service,
                                schemas=schemas,
                                spec_path=spec_path,
                            )
                        )
    return fields


def _walk_schema(
    schema: Any,
    prefix: str,
    endpoint: str,
    producer_service: str,
    schemas: dict[str, Any],
    spec_path: str,
) -> list[FieldNode]:
    resolved = _resolve_ref(schema, schemas)
    if not isinstance(resolved, dict):
        return []

    fields: list[FieldNode] = []
    properties = resolved.get("properties") or {}
    required_set = set(resolved.get("required") or [])

    for prop_name, prop_schema in properties.items():
        resolved_prop = _resolve_ref(prop_schema, schemas)
        field_path = f"{prefix}.{prop_name}"
        constraints = _extract_constraints(resolved_prop)
        declared_type = _type_label(resolved_prop)
        nullable = prop_name not in required_set or bool(
            isinstance(resolved_prop, dict) and resolved_prop.get("nullable")
        )
        fqn = f"{producer_service}::{TransportKind.REST.value}::{endpoint}::{field_path}"
        fields.append(
            FieldNode(
                fqn=fqn,
                name=prop_name,
                producer_service=producer_service,
                transport=TransportKind.REST,
                endpoint_or_topic=endpoint,
                field_path=field_path,
                declared_type=declared_type,
                nullable=nullable,
                deprecated=bool(
                    isinstance(resolved_prop, dict) and resolved_prop.get("deprecated")
                ),
                constraints=constraints,
                schema_source_path=spec_path,
            )
        )
        if isinstance(resolved_prop, dict) and resolved_prop.get("type") == "object":
            fields.extend(
                _walk_schema(
                    schema=resolved_prop,
                    prefix=field_path,
                    endpoint=endpoint,
                    producer_service=producer_service,
                    schemas=schemas,
                    spec_path=spec_path,
                )
            )
    return fields


def _resolve_ref(schema: Any, schemas: dict[str, Any]) -> Any:
    if not isinstance(schema, dict):
        return schema
    ref = schema.get("$ref")
    if not ref:
        return schema
    name = ref.rsplit("/", 1)[-1]
    target = schemas.get(name)
    if target is None:
        return schema
    merged = dict(target)
    for key, value in schema.items():
        if key != "$ref":
            merged[key] = value
    return merged


def _type_label(schema: Any) -> str:
    if not isinstance(schema, dict):
        return "unknown"
    if schema.get("type"):
        base = schema["type"]
        if base == "array":
            items = schema.get("items") or {}
            return f"array<{_type_label(items)}>"
        return str(base)
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "oneOf" in schema or "anyOf" in schema:
        return "union"
    return "object"


def _extract_constraints(schema: Any) -> list[Constraint]:
    if not isinstance(schema, dict):
        return []
    constraints: list[Constraint] = []
    mapping = {
        "minimum": "minimum",
        "maximum": "maximum",
        "minLength": "minLength",
        "maxLength": "maxLength",
        "pattern": "pattern",
        "format": "format",
        "enum": "enum",
    }
    for key, kind in mapping.items():
        if key in schema:
            value = schema[key]
            if isinstance(value, list):
                value = ",".join(str(v) for v in value)
            else:
                value = str(value)
            constraints.append(Constraint(kind=kind, value=value, source="openapi"))
    return constraints
