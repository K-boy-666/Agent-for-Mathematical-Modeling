# numerical.root_finding 1.0 稳定契约

能力 ID/契约版本是 `numerical.root_finding/1.0.0`；实现 ID 是
`builtin.numerical.root_finding.bisection`，实现版本独立演进。数据形状权威为：

- [input.schema.json](../../src/modeling_capabilities/root_finding/schemas/1.0.0/input.schema.json)
- [canonical-input.schema.json](../../src/modeling_capabilities/root_finding/schemas/1.0.0/canonical-input.schema.json)
- [success-data.schema.json](../../src/modeling_capabilities/root_finding/schemas/1.0.0/success-data.schema.json)
- [failure-data.schema.json](../../src/modeling_capabilities/root_finding/schemas/1.0.0/failure-data.schema.json)
- [policy.schema.json](../../src/modeling_capabilities/root_finding/schemas/1.0.0/policy.schema.json)
- [report.schema.json](../../src/modeling_capabilities/root_finding/schemas/1.0.0/report.schema.json)

## 版本轴

API 版本是 `modeling-capability/1.0.0`；契约版本是 `numerical.root_finding/1.0.0`；
实现版本标识具体二分法代码；策略版本是 `numerical.root_finding.residual/1.0.0`；
报告版本是 `modeling-validation-report/1.0.0`。Canonical input 版本是
`numerical.root_finding.canonical-input/1.0.0`，不与原始输入版本混用。

## 数学语义

输入是有限区间、受限 `math-expr-v1` 表达式、三种正容差和迭代上限。缺省值规范化后物化，
持久化 AST 而非原始表达式。二分法要求端点已满足 residual 容差或形成符号变化；无符号变化、
预算耗尽或表达式在区间内无定义返回稳定数值失败，不是 MCP 系统错误。

有效示例：`x**2-2`、区间 `[0, 2]`。无效示例：`__import__('os')` 被语法白名单拒绝；
`x**2+1`、区间 `[-1, 1]` 没有符号变化，产生数值失败而不伪造 root。

独立 residual Validator 重新解析规范 AST、重新求值并检查区间、有限值、报告值差和 residual 容差；
哈希自洽但数学结果伪造的输入必须得到 `FAILED`。方法、条件数限制和 focused verify 命令见
[能力局部 context](../../src/modeling_capabilities/root_finding/context.md)，通用边界见
[Capability API v1](capability-api-v1.md)。
