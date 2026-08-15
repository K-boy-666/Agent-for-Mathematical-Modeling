# M1a Context 索引

当前里程碑：M1a A12.3，建立最小 context 路由；A12.4 才实现验收策略。

## 权威入口

- 当前接口补充：[A12 接口决议](../superpowers/specs/2026-08-11-m1a-a12-interface-resolution.md)
- 原始批准设计：[M1 设计](../superpowers/specs/2026-07-16-math-modeling-mcp-design.md)
- 任务与抽象预算：[M1 实施计划](../superpowers/plans/2026-07-17-math-modeling-mcp-m1.md)
- 仓库执行规则：[根 AGENTS](../../AGENTS.md)

冲突顺序：用户明确指令 → 后续批准补充 → 原始设计 → 实施计划 → 本索引及摘要。
JSON Schema 始终是数据形状权威。

## 主题路由

- 产品范围与阶段门：[M1 范围](../product/m1-scope.md)
- 模块和依赖方向：[架构概览](../architecture/overview.md)
- 六工具 0.1 契约：[MCP tools v0](../contracts/mcp-tools-v0.md)
- Built-in Capability 0.1 契约：[Capability API v0](../contracts/capability-api-v0.md)
- 求根 0.1 契约：[root finding v0](../contracts/root-finding-v0.md)
- 本地状态与诊断：[bootstrap 与 doctor](../operations/bootstrap-and-doctor.md)
- Codex 配置模板：[config.toml](../templates/codex/config.toml)

## 任务到最小上下文

| 工作 | 最少阅读 |
|---|---|
| 核心或状态 | 根规则、M1 范围、架构概览、对应嵌套规则 |
| MCP 工具 | 根规则、MCP tools v0、`modeling_mcp/AGENTS.md` |
| 数学能力 | Capability API v0、root finding v0、能力局部 context |
| bootstrap/doctor | 运维文档、架构概览、A12 接口决议 |
| 测试或 verify | 根规则、`tests/AGENTS.md`、A12 接口决议 §4.3 |

## 能力发现

运行 `list_capabilities` 获取已封存注册表中的当前能力。
当前唯一能力是 `numerical.root_finding/0.1.0`；能力目录不是插件市场。

## 验收路由

M1a 完整验证入口是 `uv run --locked --no-sync modeling verify --milestone m1a`。
A-01–A-10 的字面测试节点与证据语义以 A12 接口决议 §4.3 为准；本索引不复制策略。

## 弃用

文档或 0.x 契约被替换时，先更新本索引指向单一新权威源。
删除旧路由前完成调用方迁移；不要保留两份可编辑 Schema 或契约正文。
