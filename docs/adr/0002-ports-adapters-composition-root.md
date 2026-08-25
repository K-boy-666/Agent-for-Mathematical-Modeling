# ADR 0002: 端口、适配器与唯一组合根

- Status: Accepted
- Date: 2026-07-17

## Context

MCP、CLI、数学与 SQLite 必须可独立测试，且宿主名称不能进入核心 DTO 或持久状态。

## Decision

MCP 与 CLI 只调用 `ApplicationFacade`；`ModelingApplication` 只通过用例形状的端口访问基础设施。
唯一组合根显式装配 `SQLiteProjectStore`、能力注册表、时钟和 ID 生成器。当前调用方是 MCP、doctor
和直接应用测试。

## Consequences

依赖方向清晰，测试可替换少量端口；组合根承担所有具体实现知识并必须保持唯一。

## Rejected Alternatives

拒绝服务定位器、反射式 DI、通用 Repository 基类和宿主专属核心，因为当前没有第二实现需要它们。
