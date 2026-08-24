# Built-in Capability 目录

本页只提供发现摘要。数据形状以版本化 Schema 为准，数学细节按需从局部 context 加载。

| capability_id | contract_version | status | summary | context | contract | tests |
|---|---|---|---|---|---|---|
| `numerical.root_finding` | `1.0.0` | stable | 有限区间内的二分求根与独立 residual 验证 | [context](../../src/modeling_capabilities/root_finding/context.md) · [descriptor](../../src/modeling_capabilities/root_finding/descriptor.py) | [Capability API 语义](../contracts/capability-api-v1.md) · [求根语义](../contracts/root-finding-v1.md) · [1.0 Schemas](../../src/modeling_capabilities/root_finding/schemas/1.0.0/) | `uv run --locked --no-sync modeling verify --capability numerical.root_finding` |

新增能力使用 `add-capability` Skill，并在唯一组合根显式注册。
