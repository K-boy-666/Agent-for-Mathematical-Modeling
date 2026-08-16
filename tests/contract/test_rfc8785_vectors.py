"""B2 RFC 8785 canonical JSON vectors — dependency conformance and project lane."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
import rfc8785

from modeling_core.contracts.canonical_json import (
    canonical_json_bytes,
    sha256_json,
    strict_json_loads,
)

CORPUS = Path(__file__).parent / "corpus" / "rfc8785"


def _read_corpus(name: str) -> bytes:
    path = CORPUS / name
    assert path.is_file(), f"corpus file {name} is missing"
    return path.read_bytes()


def _read_corpus_json(name: str) -> object:
    return json.loads(_read_corpus(name).decode("utf-8"))


# ── Dependency-conformance lane ──────────────────────────────────────


class TestRFC8785AppendixB:
    """Every number row from RFC 8785 Appendix B, raw IEEE-754 bit patterns."""

    def _unpack_double(self, hex_bits: str) -> float:
        return struct.unpack(">d", bytes.fromhex(hex_bits))[0]

    def test_b01_zero(self) -> None:
        appendix = _read_corpus_json("appendix-b.json")
        row = appendix["b01"]
        value = self._unpack_double(row["hex"])
        assert rfc8785.dumps(value) == row["expected"].encode("utf-8")

    def test_b02_negative_zero(self) -> None:
        appendix = _read_corpus_json("appendix-b.json")
        row = appendix["b02"]
        value = self._unpack_double(row["hex"])
        assert rfc8785.dumps(value) == row["expected"].encode("utf-8")

    def test_b03_positive_one(self) -> None:
        appendix = _read_corpus_json("appendix-b.json")
        row = appendix["b03"]
        value = self._unpack_double(row["hex"])
        assert rfc8785.dumps(value) == row["expected"].encode("utf-8")

    def test_b04_negative_one(self) -> None:
        appendix = _read_corpus_json("appendix-b.json")
        row = appendix["b04"]
        value = self._unpack_double(row["hex"])
        assert rfc8785.dumps(value) == row["expected"].encode("utf-8")

    def test_b05_one_and_half(self) -> None:
        appendix = _read_corpus_json("appendix-b.json")
        row = appendix["b05"]
        value = self._unpack_double(row["hex"])
        assert rfc8785.dumps(value) == row["expected"].encode("utf-8")

    def test_b06_max_int(self) -> None:
        appendix = _read_corpus_json("appendix-b.json")
        row = appendix["b06"]
        value = self._unpack_double(row["hex"])
        assert rfc8785.dumps(value) == row["expected"].encode("utf-8")

    def test_b07_min_int(self) -> None:
        appendix = _read_corpus_json("appendix-b.json")
        row = appendix["b07"]
        value = self._unpack_double(row["hex"])
        assert rfc8785.dumps(value) == row["expected"].encode("utf-8")

    def test_b08_max_uint(self) -> None:
        appendix = _read_corpus_json("appendix-b.json")
        row = appendix["b08"]
        value = self._unpack_double(row["hex"])
        assert rfc8785.dumps(value) == row["expected"].encode("utf-8")

    def test_b09_smallest_denorm(self) -> None:
        appendix = _read_corpus_json("appendix-b.json")
        row = appendix["b09"]
        value = self._unpack_double(row["hex"])
        assert rfc8785.dumps(value) == row["expected"].encode("utf-8")

    def test_b10_smallest_norm(self) -> None:
        appendix = _read_corpus_json("appendix-b.json")
        row = appendix["b10"]
        value = self._unpack_double(row["hex"])
        assert rfc8785.dumps(value) == row["expected"].encode("utf-8")

    def test_b11_largest_norm(self) -> None:
        appendix = _read_corpus_json("appendix-b.json")
        row = appendix["b11"]
        value = self._unpack_double(row["hex"])
        assert rfc8785.dumps(value) == row["expected"].encode("utf-8")

    def test_b12_one_third(self) -> None:
        appendix = _read_corpus_json("appendix-b.json")
        row = appendix["b12"]
        value = self._unpack_double(row["hex"])
        assert rfc8785.dumps(value) == row["expected"].encode("utf-8")

    def test_b13_pi(self) -> None:
        appendix = _read_corpus_json("appendix-b.json")
        row = appendix["b13"]
        value = self._unpack_double(row["hex"])
        assert rfc8785.dumps(value) == row["expected"].encode("utf-8")

    def test_b14_e(self) -> None:
        appendix = _read_corpus_json("appendix-b.json")
        row = appendix["b14"]
        value = self._unpack_double(row["hex"])
        assert rfc8785.dumps(value) == row["expected"].encode("utf-8")

    def test_b15_smallest_positive(self) -> None:
        appendix = _read_corpus_json("appendix-b.json")
        row = appendix["b15"]
        value = self._unpack_double(row["hex"])
        assert rfc8785.dumps(value) == row["expected"].encode("utf-8")


class TestUpstreamCorpus:
    """Six upstream input/output pairs byte-for-byte from cyberphone/json-canonicalization."""

    def _assert_roundtrip(self, name: str) -> None:
        input_bytes = _read_corpus(f"{name}.input.json")
        output_bytes = _read_corpus(f"{name}.output.json")
        value = json.loads(input_bytes.decode("utf-8"))
        canonical = rfc8785.dumps(value)
        assert canonical == output_bytes

    def test_arrays(self) -> None:
        self._assert_roundtrip("arrays")

    def test_french(self) -> None:
        self._assert_roundtrip("french")

    def test_structures(self) -> None:
        self._assert_roundtrip("structures")

    def test_unicode(self) -> None:
        self._assert_roundtrip("unicode")

    def test_values(self) -> None:
        self._assert_roundtrip("values")

    def test_weird(self) -> None:
        self._assert_roundtrip("weird")


# ── Project lane ─────────────────────────────────────────────────────


class TestProjectNormalization:
    """Project normalization: NFC, negative zero, 1 vs 1.0, defaults, whitespace."""

    def test_nfc_normalization_applied(self) -> None:
        """Combining sequences are normalized to composed form."""
        a_combining = "a\u0301"
        a_composed = "\u00e1"
        assert canonical_json_bytes({"key": a_combining}) == canonical_json_bytes(
            {"key": a_composed}
        )

    def test_nfc_duplicate_keys_rejected(self) -> None:
        """Keys that collide after NFC normalization are rejected."""
        a_combining = "a\u0301"
        a_composed = "\u00e1"
        with pytest.raises(ValueError, match="NFC"):
            canonical_json_bytes({a_combining: 1, a_composed: 2})

    def test_negative_zero_normalized(self) -> None:
        """Negative zero is normalized to 0."""
        assert canonical_json_bytes(-0.0) == canonical_json_bytes(0.0)

    def test_one_and_one_point_zero_are_equivalent(self) -> None:
        """1 and 1.0 are equivalent in canonical JSON (both produce b'1')."""
        assert canonical_json_bytes(1) == b"1"
        assert canonical_json_bytes(1.0) == b"1"

    def test_nan_rejected(self) -> None:
        """NaN must be rejected."""
        with pytest.raises(ValueError, match="finite"):
            canonical_json_bytes(float("nan"))

    def test_positive_infinity_rejected(self) -> None:
        """Positive infinity must be rejected."""
        with pytest.raises(ValueError, match="finite"):
            canonical_json_bytes(float("inf"))

    def test_negative_infinity_rejected(self) -> None:
        """Negative infinity must be rejected."""
        with pytest.raises(ValueError, match="finite"):
            canonical_json_bytes(float("-inf"))

    def test_lone_surrogate_rejected(self) -> None:
        """Lone surrogates must be rejected."""
        with pytest.raises(ValueError, match="surrogate"):
            canonical_json_bytes("\ud800")

    def test_strict_json_loads_rejects_infinity(self) -> None:
        """strict_json_loads rejects Infinity text."""
        with pytest.raises(ValueError, match="non-finite"):
            strict_json_loads(b"Infinity")

    def test_strict_json_loads_rejects_nan(self) -> None:
        """strict_json_loads rejects NaN text."""
        with pytest.raises(ValueError, match="non-finite"):
            strict_json_loads(b"NaN")

    def test_strict_json_loads_rejects_duplicate_keys(self) -> None:
        """strict_json_loads rejects duplicate object keys."""
        with pytest.raises(ValueError, match="duplicate"):
            strict_json_loads(b'{"a":1,"a":2}')

    def test_strict_json_loads_rejects_lone_surrogate(self) -> None:
        """strict_json_loads rejects lone surrogates in JSON strings."""
        with pytest.raises(ValueError, match="surrogate"):
            strict_json_loads(b'["\\ud800"]')

    def test_strict_json_loads_rejects_invalid_utf8(self) -> None:
        """strict_json_loads rejects invalid UTF-8."""
        with pytest.raises(ValueError, match="UTF-8"):
            strict_json_loads(b"\xff\xfe")


class TestProjectVectors:
    """Project-level vectors from project-vectors.json."""

    def test_project_vectors_exist(self) -> None:
        """project-vectors.json must be a non-empty array."""
        vectors = _read_corpus_json("project-vectors.json")
        assert isinstance(vectors, list)
        assert len(vectors) > 0

    def test_project_vector_consistency(self) -> None:
        """Each project vector must produce the expected canonical hash."""
        vectors = _read_corpus_json("project-vectors.json")
        for vector in vectors:
            label = vector["label"]
            value = vector["value"]
            expected_hash = vector["sha256"]
            actual_hash = sha256_json(value)  # type: ignore[arg-type]
            assert actual_hash == expected_hash, f"vector {label} hash mismatch"


class TestFixedHashSmoke:
    """M1a smoke vectors remain stable."""

    def test_empty_array_hash(self) -> None:
        assert sha256_json([]) == (
            "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
        )

    def test_empty_object_hash(self) -> None:
        assert sha256_json({}) == (
            "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
        )

    def test_negative_zero_ordering(self) -> None:
        assert canonical_json_bytes({"b": 1.0, "a": -0.0}) == b'{"a":0,"b":1}'
