# MCP tools 1.0 稳定契约

应用 `0.2.0` 只声明 MCP 协议 `2025-11-25`，工具契约是 `modeling-tools/1.0.0`。
传输遵守 [MCP 2025-11-25 STDIO](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)，
实现使用[官方 MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)稳定 1.x 线
（`mcp>=1.27,<2`）。Schema 使用
[JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12)。

数据形状只由打包 Schema 定义；本页解释路由、语义和兼容边界。

## 工具与 Schema

| 工具 | 语义 | request / result / error |
|---|---|---|
| `health_check` | 返回版本、注册表与有限健康状态 | [request](../../src/modeling_core/contracts/schemas/tools/1.0.0/health_check.request.schema.json) · [result](../../src/modeling_core/contracts/schemas/tools/1.0.0/health_check.result.schema.json) · [error](../../src/modeling_core/contracts/schemas/tools/1.0.0/health_check.error.schema.json) |
| `create_project` | 幂等建立唯一领域 Project | [request](../../src/modeling_core/contracts/schemas/tools/1.0.0/create_project.request.schema.json) · [result](../../src/modeling_core/contracts/schemas/tools/1.0.0/create_project.result.schema.json) · [error](../../src/modeling_core/contracts/schemas/tools/1.0.0/create_project.error.schema.json) |
| `get_project_status` | 读取摘要或有界 Experiment trace | [request](../../src/modeling_core/contracts/schemas/tools/1.0.0/get_project_status.request.schema.json) · [result](../../src/modeling_core/contracts/schemas/tools/1.0.0/get_project_status.result.schema.json) · [error](../../src/modeling_core/contracts/schemas/tools/1.0.0/get_project_status.error.schema.json) |
| `list_capabilities` | 枚举封存注册表或一个完整能力契约 | [request](../../src/modeling_core/contracts/schemas/tools/1.0.0/list_capabilities.request.schema.json) · [result](../../src/modeling_core/contracts/schemas/tools/1.0.0/list_capabilities.result.schema.json) · [error](../../src/modeling_core/contracts/schemas/tools/1.0.0/list_capabilities.error.schema.json) |
| `run_experiment` | 建立 Attempt 并运行已确认的能力输入 | [request](../../src/modeling_core/contracts/schemas/tools/1.0.0/run_experiment.request.schema.json) · [result](../../src/modeling_core/contracts/schemas/tools/1.0.0/run_experiment.result.schema.json) · [error](../../src/modeling_core/contracts/schemas/tools/1.0.0/run_experiment.error.schema.json) |
| `validate_experiment` | 独立验证已提交成功结果 | [request](../../src/modeling_core/contracts/schemas/tools/1.0.0/validate_experiment.request.schema.json) · [result](../../src/modeling_core/contracts/schemas/tools/1.0.0/validate_experiment.result.schema.json) · [error](../../src/modeling_core/contracts/schemas/tools/1.0.0/validate_experiment.error.schema.json) |
| `register_problem_assets` | 只读快照并登记 C1 问题资产 | [request](../../src/modeling_core/contracts/schemas/tools/1.0.0/register_problem_assets.request.schema.json) · [result](../../src/modeling_core/contracts/schemas/tools/1.0.0/register_problem_assets.result.schema.json) · [error](../../src/modeling_core/contracts/schemas/tools/1.0.0/register_problem_assets.error.schema.json) |
| `put_subproblem_mmir` | 写入不可变 MMIR 修订 | [request](../../src/modeling_core/contracts/schemas/tools/1.0.0/put_subproblem_mmir.request.schema.json) · [result](../../src/modeling_core/contracts/schemas/tools/1.0.0/put_subproblem_mmir.result.schema.json) · [error](../../src/modeling_core/contracts/schemas/tools/1.0.0/put_subproblem_mmir.error.schema.json) |
| `confirm_subproblem_mmir` | 用户确认精确 MMIR 修订 | [request](../../src/modeling_core/contracts/schemas/tools/1.0.0/confirm_subproblem_mmir.request.schema.json) · [result](../../src/modeling_core/contracts/schemas/tools/1.0.0/confirm_subproblem_mmir.result.schema.json) · [error](../../src/modeling_core/contracts/schemas/tools/1.0.0/confirm_subproblem_mmir.error.schema.json) |
| `export_subproblem` | 两个验证均通过后发布 C1 导出 | [request](../../src/modeling_core/contracts/schemas/tools/1.0.0/export_subproblem.request.schema.json) · [result](../../src/modeling_core/contracts/schemas/tools/1.0.0/export_subproblem.result.schema.json) · [error](../../src/modeling_core/contracts/schemas/tools/1.0.0/export_subproblem.error.schema.json) |

后四项的数据形状属于 1.0 基线，产品行为仍受
[C1 批准补充](../superpowers/specs/2026-07-23-cumcm-2022-a-q1-contest-vertical-slice-design.md)约束；
它们不暗示通用 MMIR、文件或 worker 平台已完成。

## 通用语义

所有 DTO 严格验证、拒绝未知字段。写工具以 `operation_id` 幂等；同一作用域与工具下，
同 ID 同规范请求重放结果，同 ID 异请求返回 `CONFLICT`。成功信封携带工具版本、correlation ID
和服务端时间。记录建立前的请求、版本、安全和前置条件问题使用 MCP `isError=true`；
数值失败仍是 `run_experiment` 正常结果，Validation `FAILED` 仍是验证正常结果。

有效最小健康请求是 `{}`。`{"unexpected": true}` 无效，因为未知字段被拒绝。
有效 `create_project` 请求必须带 UUID `operation_id`；重复同一规范请求返回 `replayed=true`。

## 兼容与限制

1.0 request Schema 只允许以向后兼容方式放宽；result/error 不能删除、改型或改变既有语义。
未知契约版本失败关闭。单请求上限 1 MiB，内联结果上限 256 KiB；完整限制见
[安全边界](../architecture/security.md)，版本演进见[Schema 演进](../operations/schema-evolution.md)。
