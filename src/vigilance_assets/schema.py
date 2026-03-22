from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    name: str
    sheet_header: str
    field_type: str
    required: bool
    nullable: bool
    description: str
    enum_ref: str | None = None
    fmt: str | None = None
    constraints: dict[str, Any] | None = None
    filterable: bool = False
    sortable: bool = False
    searchable: bool = False
    updatable: bool = True
    server_managed: bool = False


@dataclass(frozen=True, slots=True)
class ValidationRules:
    trl_min: int
    trl_max: int
    documentation_link_format: str
    last_updated_formats: tuple[str, ...]
    category_specific_exclusivity: bool


@dataclass(frozen=True, slots=True)
class AssetSchemaCatalog:
    """In-memory representation of the canonical asset schema."""

    schema_name: str
    version: str
    id_field: str
    common_fields: tuple[FieldDefinition, ...]
    category_fields: dict[str, tuple[FieldDefinition, ...]]
    vocabularies: dict[str, tuple[str, ...]]
    validation_rules: ValidationRules
    searchable_fields: tuple[str, ...]
    filterable_fields: tuple[str, ...]
    sortable_fields: tuple[str, ...]
    _field_definitions_by_name: dict[str, FieldDefinition] = field(init=False, repr=False)
    _common_field_names: frozenset[str] = field(init=False, repr=False)
    _all_category_field_names: frozenset[str] = field(init=False, repr=False)
    _category_field_names: dict[str, frozenset[str]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        field_definitions = {field.name: field for field in self.common_fields}
        category_field_names: dict[str, frozenset[str]] = {}
        for category, fields in self.category_fields.items():
            category_field_names[category] = frozenset(field.name for field in fields)
            for field_definition in fields:
                field_definitions[field_definition.name] = field_definition
        object.__setattr__(self, "_field_definitions_by_name", field_definitions)
        object.__setattr__(self, "_common_field_names", frozenset(field.name for field in self.common_fields))
        object.__setattr__(self, "_all_category_field_names", frozenset(field.name for fields in self.category_fields.values() for field in fields))
        object.__setattr__(self, "_category_field_names", category_field_names)

    @property
    def common_field_names(self) -> set[str]:
        return set(self._common_field_names)

    @property
    def all_category_field_names(self) -> set[str]:
        return set(self._all_category_field_names)

    def category_field_names(self, category: str) -> set[str]:
        return set(self._category_field_names[category])

    def field_definition(self, field_name: str) -> FieldDefinition | None:
        return self._field_definitions_by_name.get(field_name)


def _field_from_json(payload: dict[str, Any]) -> FieldDefinition:
    return FieldDefinition(
        name=payload["name"],
        sheet_header=payload["sheet_header"],
        field_type=payload["type"],
        required=payload["required"],
        nullable=payload["nullable"],
        description=payload.get("description", ""),
        enum_ref=payload.get("enum_ref"),
        fmt=payload.get("format"),
        constraints=payload.get("constraints"),
        filterable=payload.get("filterable", False),
        sortable=payload.get("sortable", False),
        searchable=payload.get("searchable", False),
        updatable=payload.get("updatable", True),
        server_managed=payload.get("server_managed", False),
    )


def load_schema_catalog(schema_path: str | Path | None = None) -> AssetSchemaCatalog:
    if schema_path is None:
        raw = json.loads(
            resources.files("vigilance_assets")
            .joinpath("resources", "assets_schema.json")
            .read_text(encoding="utf-8")
        )
    else:
        raw = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    rules = raw["validation_rules"]

    return AssetSchemaCatalog(
        schema_name=raw["schema_name"],
        version=raw["version"],
        id_field=raw["resource"]["id_field"],
        common_fields=tuple(_field_from_json(field) for field in raw["common_fields"]),
        category_fields={
            category: tuple(_field_from_json(field) for field in fields)
            for category, fields in raw["category_fields"].items()
        },
        vocabularies={name: tuple(values) for name, values in raw["vocabularies"].items()},
        validation_rules=ValidationRules(
            trl_min=rules["trl_range"]["min"],
            trl_max=rules["trl_range"]["max"],
            documentation_link_format=rules["documentation_link_format"],
            last_updated_formats=tuple(rules["last_updated_formats"]),
            category_specific_exclusivity=rules["category_specific_exclusivity"],
        ),
        searchable_fields=tuple(raw["search_defaults"]["default_searchable_fields"]),
        filterable_fields=tuple(raw["search_defaults"]["default_filterable_fields"]),
        sortable_fields=tuple(raw["search_defaults"]["default_sortable_fields"]),
    )
