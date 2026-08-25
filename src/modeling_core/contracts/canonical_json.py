from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Iterable
from typing import NoReturn, cast

import rfc8785

from modeling_core.contracts.common import JsonValue


def _reject_duplicate_keys(pairs: Iterable[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON number: {value}")


def _reject_lone_surrogates(value: object) -> None:
    if isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError("JSON contains a lone surrogate")
    elif isinstance(value, list):
        for item in value:
            _reject_lone_surrogates(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _reject_lone_surrogates(key)
            _reject_lone_surrogates(item)


def strict_json_loads(data: bytes) -> JsonValue:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("JSON must be valid UTF-8") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as error:
        raise ValueError("invalid JSON") from error
    _reject_lone_surrogates(value)
    return cast(JsonValue, value)


def _normalize(value: JsonValue) -> JsonValue:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON numbers must be finite")
        return 0.0 if value == 0.0 else value
    if isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError("canonical JSON strings cannot contain lone surrogates")
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise ValueError("object keys collide after NFC normalization")
            normalized[normalized_key] = _normalize(item)
        return normalized
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_bytes(value: JsonValue) -> bytes:
    return rfc8785.dumps(_normalize(value))


def sha256_json(value: JsonValue) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()
