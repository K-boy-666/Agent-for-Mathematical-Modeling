---
name: numerical-validation
description: Use when designing or changing a numerical Validator, tolerance rule, finite-value check, forged-result regression, or solver-validator independence boundary.
---

# Numerical Validation

## Overview

Validator 必须从输入独立重算数学结论；哈希自洽和求解成功都不是正确性证明。

## Procedure

1. 从 [Context 索引](../../../docs/context/index.md) 加载所选能力的局部 context 和契约，不加载无关能力数学。
2. 先写失败测试，并用手算常量或固定 fixture 得出期望；不得用被测 Solver 或 evaluator 生成 oracle。
3. Validator 只与 Solver 共享不可变语法、预算和契约类型，不共享搜索、遍历或数值 evaluator。
4. 分别检查报告值一致性、独立重算残差、契约容差和所有派生数值的有限性；预期数学失败产出结构化 `FAILED`，不依赖序列化异常。
5. 保留至少一个哈希自洽但数学结果伪造的 fixture，证明 Validator 能拒绝它。
6. 对代数等价变形、尺度变化、容差边界、未定义和非有限分支做最小变异检查。

## Verification

```powershell
uv run --locked --no-sync pytest tests/unit/root_finding/test_validator.py tests/architecture/test_solver_validator_independence.py -q
uv run --locked --no-sync modeling verify --capability numerical.root_finding
```

## References

- [求根契约](../../../docs/contracts/root-finding-v0.md)
- [能力 API](../../../docs/contracts/capability-api-v0.md)
- [求根局部 context](../../../src/modeling_capabilities/root_finding/context.md)
- [独立伪造 fixtures](../../../tests/fixtures/forged_results.py)

## Common mistakes

| mistake | correction |
|---|---|
| 用 Solver 计算 expected | 使用手算常量或独立 fixture |
| 只核对 hash | 独立重算数学结论 |
| 只测绝对容差 | 按契约分别验证位置、相对和函数容差 |
