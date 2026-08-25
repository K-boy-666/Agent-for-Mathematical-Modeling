# 架构概览

## 形状

系统是单发行物模块化单体：MCP/CLI 适配器 → `ApplicationFacade` → 领域、契约与封存注册表；
应用层经端口使用 SQLite 基础设施。唯一组合根装配具体实现。

依赖规则：`modeling_core` 不认识 MCP、CLI、SQLite 或具体能力；
Built-in Capability 不认识数据库、项目根或宿主；MCP 不实现数学或直接访问存储。
求解器与 Validator 保持独立数值实现。

## M1 抽象预算

| 抽象 | 当前调用方 | 当前具体实现 |
|---|---|---|
| `ApplicationFacade` | MCP、doctor、直接核心测试 | `ModelingApplication` |
| `ProjectStore` | `ModelingApplication` | `SQLiteProjectStore` |
| `Clock` | 截止时间与时间戳 | `SystemClock`；测试 `FakeClock` |
| `IdGenerator` | 实体、Session、correlation ID | `Uuid4Generator`；测试固定生成器 |
| `BuiltInCapability` | `CapabilityRegistry`、应用层 | `BisectionRootFindingCapability` |
| `CapabilityValidator` | `CapabilityRegistry`、应用层 | `ResidualRootFindingValidator` |

不得新增 `ExecutionBackend`、通用事件发布器、动态插件发现器、服务定位器、任务队列、
worker 池或第二数据库端口。M1b 增加的 `ArtifactStore`、`ArtifactSink` 与 `FaultInjector`
仍各自只有明确调用方。C1 的短生命周期 worker 是批准的单一竞赛切片，不是通用后端。

## 宿主边界

Codex 是首个薄适配宿主；Claude Code、TRAE 仅是未来薄适配宿主。
宿主只经本地 STDIO MCP 调用；核心模块、DTO 和持久字段不包含宿主名称。
应用 `0.2.0` 使用 MCP 协议 `2025-11-25`、公共契约 `1.0.0` 和数据库 Schema `2`。

## 数据与契约

公共 DTO 严格且版本化；JSON Schema 是数据形状权威。
能力专属 Schema 留在能力目录。SQLite 只由基础设施实现访问。
状态、输入、能力版本、Attempt、结果、Validation、警告和哈希形成可追踪关系。

## 设计风险登记

| 风险 | 拥有缓解 | 自动门禁 |
|---|---|---|
| 范围增长 | 规格与 ADR 审查 | 文档一致性与任务范围检查 |
| 宿主耦合 | 薄 MCP/CLI 适配器 | 依赖边界测试 |
| 求解器/验证器耦合 | 独立数值实现 | solver/validator import 测试 |
| 状态/制品不一致 | 先文件后引用与事务 | 故障注入和恢复测试 |
| 协作式超时 | 单调时钟检查；C1 受控 worker | deadline 与 worker 测试 |
| Schema 漂移 | 打包 Schema 为权威 | 兼容语料与 Schema 测试 |
| Windows 路径/进程 | `pathlib`、显式句柄关闭 | Windows/Ubuntu 同门禁 |
| 证据不可复现 | 源指纹、锁摘要、结构化报告 | M1b 证据自校验 |

## 进一步阅读

- [产品愿景](../product/vision.md)
- [状态模型](state-model.md)
- [安全边界](security.md)
- [MCP tools v1](../contracts/mcp-tools-v1.md)
- [Capability API v1](../contracts/capability-api-v1.md)
- [批准设计 §6](../superpowers/specs/2026-07-16-math-modeling-mcp-design.md)
- [实施计划抽象预算](../superpowers/plans/2026-07-17-math-modeling-mcp-m1.md)
