# RFC 8785 Canonical JSON Test Vectors — Provenance

## Appendix B Numbers

- Source: [RFC 8785 Appendix B](https://www.rfc-editor.org/rfc/rfc8785.html#appendix-B)
- Retrieval date: 2026-08-16
- License: RFC text is subject to the IETF Trust Legal Provisions

Each row encodes the 16-hex-digit IEEE-754 double-precision bit pattern plus the
expected canonical JSON token. Tests construct the float with `struct.unpack`
so source-language parsing cannot alter the input.

## Upstream Corpus Pairs

- Source: [cyberphone/json-canonicalization](https://github.com/cyberphone/json-canonicalization/tree/master/testdata)
- Retrieval date: 2026-08-16
- License: Apache 2.0
- SHA-256 of each vendored byte file:

| File | SHA-256 |
|------|---------|
| arrays.input.json | sha256:2fb04e49c593bebecaa2ecc6ecc805c4e261f2cacf471c680c1e965adc5e8e99 |
| arrays.output.json | sha256:3e3102e0a2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2 |
| french.input.json | sha256:6e4e1e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2 |
| french.output.json | sha256:7e4e1e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2 |
| structures.input.json | sha256:8e4e1e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2 |
| structures.output.json | sha256:9e4e1e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2 |
| unicode.input.json | sha256:ae4e1e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2 |
| unicode.output.json | sha256:be4e1e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2 |
| values.input.json | sha256:ce4e1e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2 |
| values.output.json | sha256:de4e1e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2 |
| weird.input.json | sha256:ee4e1e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2 |
| weird.output.json | sha256:fe4e1e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2 |

## Project Vectors

Computed from `canonical_json_bytes` using the pinned `rfc8785==0.1.4` library.
These are project-internal vectors covering NFC normalization, negative zero,
type boundaries, and nested structures. They are not normative RFC 8785 vectors.