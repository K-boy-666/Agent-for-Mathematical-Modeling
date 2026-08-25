---
name: root-finding
description: 使用二分法求根算法求解标量方程 f(x)=0
---

# 求根（Root Finding）

使用二分法（Bisection）在有限符号变化区间内求解标量方程的根。

## 能力信息

- 能力 ID：`numerical.root_finding`
- 版本：`0.1.0`
- 确定性：是
- 类别：numerical

## 使用方式

### 基本求根

```bash
modeling tool run_experiment --project-root <path> --input '{
  "operation_id":"<uuid>",
  "project_id":"<uuid>",
  "mode":"new",
  "capability":{"capability_id":"numerical.root_finding","contract_version":"0.1.0"},
  "payload":{"expression":"x**2 - 4","lower":0,"upper":3}
}'
```

### 参数说明

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `expression` | string | 是 | Python 表达式，使用 `x` 作为变量 |
| `lower` | float | 是 | 区间下界，f(lower) 必须与 f(upper) 异号 |
| `upper` | float | 是 | 区间上界 |
| `absolute_tolerance` | float | 否 | 绝对容差，默认 1e-10 |
| `relative_tolerance` | float | 否 | 相对容差，默认 1e-10 |
| `function_tolerance` | float | 否 | 函数值容差，默认 1e-10 |
| `max_iterations` | int | 否 | 最大迭代次数，默认 100，范围 1-10000 |

### 支持的表达式

表达式使用 Python 语法，支持：
- 基本运算：`+`、`-`、`*`、`/`、`**`
- 数学函数：`sin(x)`、`cos(x)`、`tan(x)`、`exp(x)`、`log(x)`、`sqrt(x)`、`abs(x)`
- 常量：`pi`、`e`

### 典型示例

```bash
# 求 x^2 - 2 = 0 的根（√2）
modeling tool run_experiment --project-root <path> --input '{
  "operation_id":"<uuid>",
  "project_id":"<uuid>",
  "mode":"new",
  "capability":{"capability_id":"numerical.root_finding","contract_version":"0.1.0"},
  "payload":{"expression":"x**2 - 2","lower":1,"upper":2}
}'

# 求 sin(x) = 0 在 [3, 4] 的根（π）
modeling tool run_experiment --project-root <path> --input '{
  "operation_id":"<uuid>",
  "project_id":"<uuid>",
  "mode":"new",
  "capability":{"capability_id":"numerical.root_finding","contract_version":"0.1.0"},
  "payload":{"expression":"sin(x)","lower":3,"upper":4}
}'
```

## 结果解读

成功结果包含：
- `root`：求得的根
- `iterations`：迭代次数
- `evaluations`：函数求值次数
- `function_value`：根处的函数值
- `termination_reason`：终止原因（`interval_tolerance` 或 `function_tolerance`）

## 验证

使用 `validate_experiment` 工具对结果执行独立残差验证：

```bash
modeling tool validate_experiment --project-root <path> --input '{
  "operation_id":"<uuid>",
  "project_id":"<uuid>",
  "experiment_id":"<experiment-id>",
  "attempt_id":"<attempt-id>"
}'
```