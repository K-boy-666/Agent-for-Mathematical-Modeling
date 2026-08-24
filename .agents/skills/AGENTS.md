# 仓库 Skills 目录规则

本文件补充[根规则](../../AGENTS.md)，作用域仅限 `.agents/skills`。

- 每个 Skill 的 frontmatter 只描述明确触发条件，正文给出步骤和验证。
- 使用渐进披露：先路由最小上下文，仅在任务需要时加载能力数学。
- Skill 链接规格、Schema、契约和局部 context，不复制其正文或字段表。
- Built-in Capability 使用显式组合注册；Skill 不引入发现、安装或 SDK 机制。
- 示例命令必须可复制，并传递规范化的裸 `capability_id`。
- 每个 Skill 单独做无 Skill 与有 Skill 的压力场景，再进入下一个 Skill。
- Skill 不是新的权威层；冲突时返回 [Context 索引](../../docs/context/index.md)。
