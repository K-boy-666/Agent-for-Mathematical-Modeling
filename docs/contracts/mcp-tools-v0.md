# MCP tools 0.1 契约路由

公开工具固定为 `health_check`、`create_project`、`get_project_status`、
`list_capabilities`、`run_experiment`、`validate_experiment`。

数据形状权威是 [18 个 request/result/error Schema](../../src/modeling_core/contracts/schemas/tools/0.1.0/)，
共享类型权威是 [common Schema](../../src/modeling_core/contracts/schemas/common/0.1.0/)。
本文不复制 JSON Schema。

MCP 适配器先验证请求 Schema 和严格 DTO，再调用 `ApplicationFacade`；
返回前验证结果。错误使用稳定的 0.1 错误信封，拒绝未知字段并脱敏异常、路径和秘密。
STDOUT 只包含协议帧。

版本、错误语义和兼容边界以
[批准设计](../superpowers/specs/2026-07-16-math-modeling-mcp-design.md)及
[A12 接口决议](../superpowers/specs/2026-08-11-m1a-a12-interface-resolution.md)为准。
