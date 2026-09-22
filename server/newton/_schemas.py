"""Internal request bounds and explicit response projections; paths never enter JSON."""

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Name = Annotated[str, Field(min_length=1, max_length=200)]
ShortText = Annotated[str, Field(max_length=200)]
Description = Annotated[str, Field(max_length=4000)]


class Input(BaseModel):
    """Reject unknown fields so client-supplied ownership cannot be trusted by accident."""

    model_config = ConfigDict(extra="forbid")


class Credentials(Input):
    """Bound account credentials without stripping or normalizing passwords."""

    email: Annotated[str, Field(min_length=3, max_length=254)]
    password: Annotated[str, Field(min_length=12, max_length=200)]

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        """Accept conventional email addresses and normalize their login identity."""
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@\x00-\x1f]+@[^\s@\x00-\x1f]+\.[^\s@\x00-\x1f]+", value):
            raise ValueError("Enter a valid email address")
        return value


class CompanyInput(Input):
    """Company fields accepted from the owning account."""

    name: Name
    description: Description = ""

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        """Reject whitespace-only names."""
        if not value.strip():
            raise ValueError("Name must not be blank")
        return value.strip()


class MachineInput(CompanyInput):
    """Editable machine descriptors; no executable machine controls."""

    manufacturer: ShortText = ""
    model: ShortText = ""


class MachinePatch(Input):
    """Partial machine update; supplied values cannot be null."""

    name: Name | None = None
    manufacturer: ShortText | None = None
    model: ShortText | None = None
    description: Description | None = None

    @model_validator(mode="after")
    def valid_patch(self):
        """Require at least one real field and a nonblank name if supplied."""
        _nonnull_patch(self)
        if self.name is not None:
            self.name = CompanyInput.nonblank_name(self.name)
        return self


class MappingInput(Input):
    """Explicit columns and unit; timezone is required when source times are naive."""

    time_basis: Literal["absolute", "source_local"] = "absolute"
    time_column: Name
    value_column: Name
    unit: Annotated[str, Field(min_length=1, max_length=100)]
    timezone: Annotated[str, Field(min_length=1, max_length=100)] | None = None

    @field_validator("time_column", "value_column", "unit", "timezone")
    @classmethod
    def nonblank(cls, value):
        """Reject blank mapping labels without modifying original column names."""
        if value is not None and not value.strip():
            raise ValueError("Mapping values must not be blank")
        return value


class SourcePatch(Input):
    """Partial source correction preserving original bytes and their digest."""

    revision: ShortText | None = None
    mapping: MappingInput | None = None

    @model_validator(mode="after")
    def valid_patch(self):
        """Reject empty patches and explicit nulls."""
        _nonnull_patch(self)
        return self


def _nonnull_patch(value):
    if not value.model_fields_set:
        raise ValueError("Supply at least one field to update")
    if any(getattr(value, key) is None for key in value.model_fields_set):
        raise ValueError("Updated fields cannot be null")


def project(record, fields: str) -> dict:
    """Select only contractual public columns, retaining aware ISO timestamps."""
    result = {field: getattr(record, field) for field in fields.split()}
    return {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in result.items()
    }


def company_json(company) -> dict:
    """Return a company without disclosing internal ownership columns."""
    return project(company, "id name description created_at")


def machine_json(machine) -> dict:
    """Return all contractual machine columns."""
    return project(
        machine, "id company_id name manufacturer model description context_version created_at"
    )


def source_json(source) -> dict:
    """Return source metadata without its private storage path."""
    result = project(
        source,
        "id company_id machine_id filename media_type sha256 kind status "
        "revision version mapping data_class created_at",
    )
    return {**result, "metadata": source.metadata_json}
