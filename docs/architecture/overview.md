# 架构概览

## 形状

系统是单发行物模块化单体：MCP/CLI 适配器 → `ApplicationFacade` → 领域、契约与封存注册表；
应用层经端口使用 SQLite 基础设施。唯一组合根装配具体实现。

依赖规则：`modeling_core` 不认识 MCP、CLI、SQLite 或具体能力；
Built-in Capability 不认识数据库、项目根或宿主；MCP 不实现数学或直接访问存储。
求解器与 Validator 保持独立数值实现。

## M1a 抽象预算

| 抽象 | 当前调用方 | 当前具体实现 |
|---|---|---|
| `ApplicationFacade` | MCP、doctor、直接核心测试 | `ModelingApplication` |
| `ProjectStore` | `ModelingApplication` | `SQLiteProjectStore` |
| `Clock` | 截止时间与时间戳 | `SystemClock`；测试 `FakeClock` |
| `IdGenerator` | 实体、Session、correlation ID | `Uuid4Generator`；测试固定生成器 |
| `BuiltInCapability` | `CapabilityRegistry`、应用层 | `BisectionRootFindingCapability` |
| `CapabilityValidator` | `CapabilityRegistry`、应用层 | `ResidualRootFindingValidator` |

不得新增 `ExecutionBackend`、通用事件发布器、动态插件发现器、服务定位器、任务队列、
worker 池或第二数据库端口。`ArtifactStore`、`ArtifactSink` 与 `FaultInjector` 属于 M1b。

## 数据与契约

公共 DTO 严格且版本化；JSON Schema 是数据形状权威。
能力专属 Schema 留在能力目录。SQLite 只由基础设施实现访问。
状态、输入、能力版本、Attempt、结果、Validation、警告和哈希形成可追踪关系。

## 进一步阅读

- [M1 范围](../product/m1-scope.md)
- [MCP tools v0](../contracts/mcp-tools-v0.md)
- [Capability API v0](../contracts/capability-api-v0.md)
- [批准设计 §6](../superpowers/specs/2026-07-16-math-modeling-mcp-design.md)
- [实施计划抽象预算](../superpowers/plans/2026-07-17-math-modeling-mcp-m1.md)
