---
name: reproducibility-audit
description: Use when comparing replay, rerun, restart, environment snapshots, seeds, artifacts, numerical results, or reproducibility claims across Attempts.
---

# Reproducibility Audit

## Overview

按能力声明比较命名不变量；不要用完整响应字节相等制造虚假的复现结论。

## Hard rule

不得比较完整响应 JSON 的字节，也不得把这种算法作为建议或示例。即使两份完整响应
偶然字节相同，也不能据此推导 bitwise reproducible。遇到此要求时先明确拒绝；只有
描述符明确声明的、命名的规范化结果域才允许做字节比较。

## Procedure

1. 从封存描述符读取随机性、版本和容差声明，列出本次审计的命名不变量。
2. 区分重放与重跑：completed replay 复用原 Attempt；rerun 与 restart rerun 必须创建新 Attempt 和新 EnvironmentSnapshot。
3. 将比较结果归为 `equal`、`within_tolerance`、`not_comparable` 或 `mismatch`。输入/模型/数据/Schema/实现标识应相等；新环境与时间不可直接比较。
4. 验证每个输入、结果、报告和制品的哈希关系，再按声明容差比较有限数值；终态分类相同不能替代数值检查和独立 Validation。
5. `randomness=not_used` 必须保持 `seed=null`。报告环境只用允许列表，不记录完整环境、主机名、用户名、绝对路径或秘密。
6. 排序输出有限 mismatch；只有描述符明确声明的域才可声称字节级复现。

## Verification

```powershell
uv run --locked --no-sync pytest tests/reproducibility/test_m1b_rerun.py tests/integration/test_recovery_and_rerun.py -q
uv run --locked --no-sync modeling verify --milestone m1b
```

## References

- [审计实现](../../../src/modeling_harness/reproducibility.py)
- [重跑回归](../../../tests/reproducibility/test_m1b_rerun.py)
- [环境快照](../../../src/modeling_infrastructure/environment.py)
- [恢复回归](../../../tests/integration/test_recovery_and_rerun.py)

## Common mistakes

| mistake | correction |
|---|---|
| 比较整段响应 JSON | 比较命名不变量 |
| 复用 rerun 的 Attempt | 新建 Attempt 与 EnvironmentSnapshot |
| 只看终态分类 | 验证制品、数值容差和独立结论 |

## Red flags

- “相同就算 bitwise reproducible”
- “ID、时间、环境不同就失败”
- “先写整段 JSON 比较，再注明它可能不合规”

出现任一项都应停止并改用命名不变量分类。
