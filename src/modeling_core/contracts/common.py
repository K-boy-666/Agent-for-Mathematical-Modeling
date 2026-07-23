from __future__ import annotations

import re
import unicodedata
from typing import Annotated, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

EntityId = Annotated[
    str,
    StringConstraints(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
]
Hash = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
Timestamp = Annotated[
    str,
    StringConstraints(
        pattern=r"^(?:[0-9]{4})-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
        r"T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{3}Z$"
    ),
]
Version = Annotated[
    str,
    StringConstraints(pattern=r"^(?:[A-Za-z0-9_.-]+/)?0\.1\.0$"),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class Warning(StrictModel):
    code: Annotated[str, Field(min_length=1)]
    message: Annotated[str, Field(min_length=1)]

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        if unicodedata.normalize("NFC", value) != value:
            raise ValueError("warning message must be NFC-normalized")
        if len(value.encode("utf-8")) > 1024:
            raise ValueError("warning message exceeds 1024 UTF-8 bytes")
        if any(unicodedata.category(char) == "Cc" for char in value):
            raise ValueError("warning message contains a control character")
        if re.search(r"(?:[A-Za-z]:[\\/]|/(?:[^/\0]+/)+)", value):
            raise ValueError("warning message must not contain an absolute path")
        return value


class RegistrySummary(StrictModel):
    sealed: bool
    fingerprint: Hash
    capability_count: Annotated[int, Field(ge=0)]


class ProjectSummary(StrictModel):
    project_id: EntityId
    display_name: Annotated[str, Field(min_length=1, max_length=128)]
    project_format_version: str
    project_state: Annotated[str, Field(pattern=r"^READY$")]
    created_at: Timestamp
