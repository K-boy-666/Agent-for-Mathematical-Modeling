---
name: coupled-heave
description: 耦合垂荡动力学求解器 — 浮子与振子系统的 ODE 仿真
---

# 耦合垂荡动力学（Coupled Heave Dynamics）

求解浮子（float）与振子（oscillator）耦合垂荡系统的 ODE，支持线性阻尼和幂律阻尼两种模式。

## 能力信息

- 能力 ID：`dynamics.coupled_heave`
- 版本：`0.1.0`
- 确定性：是
- 类别：dynamics

## 数学模型

```
(m_f + m_a) x_f'' + B x_f' + K_h x_f + k(x_f - x_o) + D(x_f' - x_o') = F cos(ωt)
m_o x_o'' + k(x_o - x_f) + D(x_o' - x_f') = 0
K_h = ρ g π r²
```

## 参数

| 参数 | 值 | 单位 | 说明 |
|------|-----|------|------|
| ω | 1.4005 | s⁻¹ | 激励频率 |
| m_a | 1335.535 | kg | 附加质量 |
| B | 656.3616 | N·s/m | 粘性阻尼 |
| F | 6250 | N | 激励幅值 |
| m_f | 4866 | kg | 浮子质量 |
| m_o | 2433 | kg | 振子质量 |
| r | 1.0 | m | 浮子半径 |
| ρ | 1025 | kg/m³ | 水密度 |
| g | 9.8 | m/s² | 重力加速度 |
| k | 80000 | N/m | 弹簧刚度 |

## 阻尼模式

### 线性阻尼

```
D(q) = 10000·q
```

### 幂律阻尼

```
D(q) = 10000·|q|^0.5·q
```

## 求解器配置

- 方法：DOP853（8 阶显式 Runge-Kutta）
- 相对容差：1e-9
- 绝对容差：1e-11
- 输出网格：898 点，步长 0.2s，终点 179.4s
- 硬超时：60 秒

## 使用方式

通过 C1 工作流使用（需要先注册资产、提交和确认 MMIR）：

```bash
# 1. 注册资产
modeling tool register_problem_assets --project-root <path> --input '{
  "operation_id":"<uuid>",
  "project_id":"<uuid>",
  "assets":[{"label":"A题.pdf","path":"<path>"}]
}'

# 2. 提交 MMIR
modeling tool put_subproblem_mmir --project-root <path> --input '{
  "operation_id":"<uuid>",
  "project_id":"<uuid>",
  "subproblem_id":"CUMCM-2022-A-Q1",
  "mmir_content":"<markdown>"
}'

# 3. 确认 MMIR 版本
modeling tool confirm_subproblem_mmir --project-root <path> --input '{
  "operation_id":"<uuid>",
  "project_id":"<uuid>",
  "subproblem_id":"CUMCM-2022-A-Q1",
  "revision":"<hash>"
}'
```

## 独立验证

- 线性阻尼：使用增广状态矩阵指数（matrix exponential）作为参考解
- 幂律阻尼：使用独立固定步长 RK4（步长 0.01s 和 0.005s）作为参考解
- 生产/参考容差：rtol=2e-4、atol=2e-6
- 归一化能量闭合误差：≤ 1e-3
- 求解器与验证器互不导入

## 导出

需两次验证（线性 + 幂律）均 PASSED 后才能导出：

```bash
modeling tool export_subproblem --project-root <path> --input '{
  "operation_id":"<uuid>",
  "project_id":"<uuid>",
  "subproblem_id":"CUMCM-2022-A-Q1"
}'
```