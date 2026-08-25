# root finding 0.1 契约路由

能力 ID 是 `numerical.root_finding/0.1.0`。

输入、规范输入、策略、成功、失败和验证报告的数据形状权威位于
[root finding Schema](../../src/modeling_capabilities/root_finding/schemas/0.1.0/)。
表达式语法、预算和规范化规则见
[能力局部 context](../../src/modeling_capabilities/root_finding/context.md)。
本文不复制 JSON Schema。

当前实现使用确定性二分法；无符号变化返回稳定数值失败。
非法表达式在 Attempt 建立前拒绝。Validator 不导入求解器 evaluator，
并使用独立计算拒绝 root 或 function value 伪造的结果。

通用能力边界见 [Capability API v0](capability-api-v0.md)。
