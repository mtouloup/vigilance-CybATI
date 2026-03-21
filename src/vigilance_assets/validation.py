from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable
from urllib.parse import urlparse

from .models import build_asset_record
from .schema import AssetSchemaCatalog, FieldDefinition, load_schema_catalog


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    field: str
    message: str
    code: str


class ValidationError(ValueError):
    def __init__(self, issues: Iterable[ValidationIssue]):
        self.issues = list(issues)
        super().__init__("; ".join(f"{issue.field}: {issue.message}" for issue in self.issues))


class AssetValidator:
    def __init__(self, catalog: AssetSchemaCatalog | None = None) -> None:
        self.catalog = catalog or load_schema_catalog()

    def validate_for_create(
        self,
        payload: dict[str, Any],
        existing_asset_ids: set[str] | None = None,
    ):
        issues = self._validate_payload(payload, partial=False, existing_asset_ids=existing_asset_ids)
        if issues:
            raise ValidationError(issues)
        return build_asset_record(payload)

    def validate_for_patch(self, category: str, payload: dict[str, Any]):
        merged = {"Asset_Category": category, **payload}
        issues = self._validate_payload(merged, partial=True, existing_asset_ids=None)
        if issues:
            raise ValidationError(issues)
        return merged

    def _validate_payload(
        self,
        payload: dict[str, Any],
        *,
        partial: bool,
        existing_asset_ids: set[str] | None,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        category = payload.get("Asset_Category")

        known_fields = self.catalog.common_field_names | self.catalog.all_category_field_names
        for field in payload:
            if field not in known_fields:
                issues.append(ValidationIssue(field, "Unknown field.", "unknown_field"))

        for field_def in self.catalog.common_fields:
            issues.extend(self._validate_field(field_def, payload, partial=partial))

        if category is None:
            if not partial:
                issues.append(ValidationIssue("Asset_Category", "Field is required.", "required"))
            return issues
        if category not in self.catalog.category_fields:
            issues.append(ValidationIssue("Asset_Category", "Unsupported asset category.", "invalid_choice"))
            return issues

        for field_def in self.catalog.category_fields[category]:
            issues.extend(self._validate_field(field_def, payload, partial=partial))

        if self.catalog.validation_rules.category_specific_exclusivity:
            allowed = self.catalog.category_field_names(category)
            disallowed = self.catalog.all_category_field_names - allowed
            for field_name in disallowed:
                if self._is_populated(payload.get(field_name)):
                    issues.append(
                        ValidationIssue(
                            field_name,
                            f"Field is not allowed for category '{category}'.",
                            "category_exclusive",
                        )
                    )

        asset_id = payload.get(self.catalog.id_field)
        if not partial and asset_id in (existing_asset_ids or set()):
            issues.append(ValidationIssue(self.catalog.id_field, "Asset_ID must be unique.", "duplicate"))
        if partial and self.catalog.id_field in payload:
            issues.append(ValidationIssue(self.catalog.id_field, "Asset_ID is immutable.", "immutable"))

        return issues

    def _validate_field(
        self,
        field_def: FieldDefinition,
        payload: dict[str, Any],
        *,
        partial: bool,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        field_name = field_def.name
        present = field_name in payload
        value = payload.get(field_name)

        if field_def.required and not partial and not self._is_populated(value):
            issues.append(ValidationIssue(field_name, "Field is required.", "required"))
            return issues
        if partial and not present:
            return issues
        if value is None or value == "":
            if not field_def.nullable and present and field_def.required:
                issues.append(ValidationIssue(field_name, "Field cannot be empty.", "null_not_allowed"))
            return issues

        if field_def.field_type == "integer":
            if not isinstance(value, int):
                issues.append(ValidationIssue(field_name, "Field must be an integer.", "invalid_type"))
            else:
                min_value = self.catalog.validation_rules.trl_min
                max_value = self.catalog.validation_rules.trl_max
                if not (min_value <= value <= max_value):
                    issues.append(
                        ValidationIssue(
                            field_name,
                            f"Field must be between {min_value} and {max_value}.",
                            "out_of_range",
                        )
                    )

        if field_def.field_type in {"string", "datetime"} and not isinstance(value, (str, date, datetime)):
            issues.append(ValidationIssue(field_name, "Field has an invalid type.", "invalid_type"))

        if field_def.enum_ref and value not in self.catalog.vocabularies[field_def.enum_ref]:
            issues.append(ValidationIssue(field_name, "Field must match a controlled vocabulary value.", "invalid_choice"))

        if field_name == "Documentation_Link" and isinstance(value, str):
            parsed = urlparse(value)
            if not parsed.scheme or not parsed.netloc:
                issues.append(ValidationIssue(field_name, "Documentation_Link must be a valid URL.", "invalid_url"))

        if field_name == "Last_Updated":
            if isinstance(value, str):
                try:
                    datetime.fromisoformat(value)
                except ValueError:
                    issues.append(
                        ValidationIssue(
                            field_name,
                            "Last_Updated must be an ISO date or datetime.",
                            "invalid_datetime",
                        )
                    )
            elif not isinstance(value, (date, datetime)):
                issues.append(
                    ValidationIssue(
                        field_name,
                        "Last_Updated must be a date or datetime.",
                        "invalid_datetime",
                    )
                )

        return issues

    @staticmethod
    def _is_populated(value: Any) -> bool:
        return value not in (None, "")
