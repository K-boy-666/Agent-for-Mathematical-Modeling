# M1b Context 索引

当前里程碑：M1b B10，发布稳定架构、契约、运维与决策基线。

## 权威入口

- [批准设计](../superpowers/specs/2026-07-16-math-modeling-mcp-design.md)
- [C1 批准补充](../superpowers/specs/2026-07-23-cumcm-2022-a-q1-contest-vertical-slice-design.md)
- [A12 接口决议](../superpowers/specs/2026-08-11-m1a-a12-interface-resolution.md)
- [M1 实施计划](../superpowers/plans/2026-07-17-math-modeling-mcp-m1.md)
- [仓库根规则](../../AGENTS.md)

冲突权威链固定为 approved spec/accepted ADR → versioned JSON Schema → contract docs → tests → code。
发现冲突时必须 stop the task，并在 same increment 中修正所有较低权威来源。

## 主题路由

- 产品范围与路线：[产品愿景](../product/vision.md)
- 模块和依赖方向：[架构概览](../architecture/overview.md)
- 状态与安全：[状态模型](../architecture/state-model.md)、[安全边界](../architecture/security.md)
- 稳定工具语义：[MCP tools v1](../contracts/mcp-tools-v1.md)
- Built-in Capability 语义：[Capability API v1](../contracts/capability-api-v1.md)
- 求根语义：[root finding v1](../contracts/root-finding-v1.md)
- 本地状态与只读诊断：[bootstrap 与 doctor](../operations/bootstrap-and-doctor.md)
- 恢复与发布：[恢复手册](../operations/recovery.md)、[发布验证](../operations/release-verification.md)
- 能力摘要：[能力目录](../capabilities/index.md)

## 任务到最小上下文

每行都从根规则开始，再加载最近目录规则和一个主题来源。capability context only for the selected capability；
do not load unrelated capability mathematics。

| task | minimum rules | topic | optional Skill or capability context |
|---|---|---|---|
| code | `AGENTS.md` 与最近的嵌套 `AGENTS.md` | [architecture/overview.md](../architecture/overview.md) | 无 |
| schema | `AGENTS.md` 与拥有 Schema 的嵌套 `AGENTS.md` | [contracts/](../contracts/) 中对应语义文档 | 仅能力 Schema 使用 `add-capability` |
| sqlite-recovery | `AGENTS.md`、`modeling_infrastructure/AGENTS.md` | [operations/recovery.md](../operations/recovery.md) | `reproducibility-audit` 仅用于复现审计 |
| mcp-stdio | `AGENTS.md`、`modeling_mcp/AGENTS.md` | [contracts/mcp-tools-v1.md](../contracts/mcp-tools-v1.md) | `stdio-diagnostics` |
| numerical-method | `AGENTS.md`、`modeling_capabilities/AGENTS.md` | [root_finding/context.md](../../src/modeling_capabilities/root_finding/context.md) | `numerical-validation` 与所选能力 context |
| validator | `AGENTS.md`、`modeling_capabilities/AGENTS.md` | [contracts/capability-api-v1.md](../contracts/capability-api-v1.md) | `numerical-validation`；不加载其他求解器数学 |
| release | `AGENTS.md`、`tests/AGENTS.md` | [operations/release-verification.md](../operations/release-verification.md) | `release-verification` |
| documentation | `AGENTS.md`、`docs/AGENTS.md` | [architecture/overview.md](../architecture/overview.md) | 仅加载被修改文档的拥有来源 |

## 能力发现

运行 `list_capabilities` 获取组合时显式注册并封存的当前能力；目录不是安装市场。
先读[能力摘要](../capabilities/index.md)，只有选定能力后才加载它的局部 context。

## 验收路由

- M1a 完整门：`uv run --locked --no-sync modeling verify --milestone m1a`
- M1b 完整门：`uv run --locked --no-sync modeling verify --milestone m1b`
- 单能力反馈：`uv run --locked --no-sync modeling verify --capability numerical.root_finding`

单能力反馈不产生完成证据，也不能代替里程碑门。
