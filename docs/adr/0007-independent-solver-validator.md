# ADR 0007: 求解器与 Validator 独立

- Status: Accepted
- Date: 2026-07-17

## Context

复用求解器数值实现的验证只能证明代码自洽，不能发现伪造结果或共同算法缺陷。

## Decision

求解器和 Validator 不导入彼此的 evaluator 或数值算法；只共享不可变契约、Schema、语法 AST
与预算类型。Validator 从已提交制品独立重算。当前调用方是运行与验证用例及数学验收 Harness。

## Consequences

存在有意的少量重复，但 Validation 能拒绝哈希自洽而数学伪造的结果；数值容差必须显式版本化。

## Rejected Alternatives

拒绝“求解成功即验证通过”、共享 evaluator、只比哈希或只检查结果 Schema，因为它们不独立。
