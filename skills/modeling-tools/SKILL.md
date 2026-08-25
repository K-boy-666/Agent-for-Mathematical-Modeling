---
name: modeling-tools
description: 数学建模工具完整参考 — 10 个工具的 CLI 调用方式
---

# 数学建模工具参考

本 Skill 提供全部 10 个数学建模工具的 CLI 调用方式。所有工具通过 `modeling tool` 命令调用，需要指定 `--project-root`（项目根目录）和 `--input`（JSON 参数）。

## 前置条件

项目必须已通过 `modeling bootstrap --project-root <path>` 初始化。

## 工具列表

### 1. health_check — 健康检查

检查系统状态、SQLite 可用性、能力注册表状态。

```bash
modeling tool health_check --project-root <path> --input '{}'
```

### 2. create_project — 创建项目

创建一个新的数学建模项目。

```bash
modeling tool create_project --project-root <path> --input '{"operation_id":"<uuid>","display_name":"<name>"}'
```

参数：
- `operation_id`：UUID 格式的操作 ID（幂等键）
- `display_name`（可选）：项目名称，1-128 字符

### 3. get_project_status — 查询项目状态

查询项目摘要或实验详情。

```bash
# 查询摘要
modeling tool get_project_status --project-root <path> --input '{"project_id":"<uuid>","view":"summary"}'

# 查询实验详情
modeling tool get_project_status --project-root <path> --input '{"project_id":"<uuid>","view":"experiment","experiment_id":"<uuid>"}'
```

### 4. list_capabilities — 列出能力

列出已注册的能力及其合约信息。

```bash
# 能力摘要
modeling tool list_capabilities --project-root <path> --input '{}'

# 指定能力
modeling tool list_capabilities --project-root <path> --input '{"capability_id":"numerical.root_finding"}'

# 获取合约详情
modeling tool list_capabilities --project-root <path> --input '{"detail":"contract","capability_id":"numerical.root_finding","contract_version":"0.1.0"}'
```

### 5. run_experiment — 运行实验

执行一个数学建模实验。

```bash
modeling tool run_experiment --project-root <path> --input '{
  "operation_id":"<uuid>",
  "project_id":"<uuid>",
  "mode":"new",
  "capability":{"capability_id":"numerical.root_finding","contract_version":"0.1.0"},
  "payload":{"expression":"x**2 - 4","lower":0,"upper":3}
}'
```

参数：
- `operation_id`：UUID 格式的操作 ID
- `project_id`：项目 ID
- `mode`：`"new"` 创建新实验
- `capability`：能力 ID 和版本
- `payload`：能力特定参数（求根：`expression`、`lower`、`upper`）
- `execution`（可选）：`timeout_ms`（1-60000，默认 10000）、`seed`

### 6. validate_experiment — 验证实验

对实验结果执行独立验证。

```bash
modeling tool validate_experiment --project-root <path> --input '{
  "operation_id":"<uuid>",
  "project_id":"<uuid>",
  "experiment_id":"<uuid>",
  "attempt_id":"<uuid>"
}'
```

### 7. register_problem_assets — 注册题目资产（C1 预览）

注册竞赛题目官方资产的内容寻址快照。

```bash
modeling tool register_problem_assets --project-root <path> --input '{
  "operation_id":"<uuid>",
  "project_id":"<uuid>",
  "assets":[{"label":"A题.pdf","path":"<absolute-path>"}]
}'
```

### 8. put_subproblem_mmir — 提交子问题 MMIR（C1 预览）

提交子问题的数学建模解释记录。

```bash
modeling tool put_subproblem_mmir --project-root <path> --input '{
  "operation_id":"<uuid>",
  "project_id":"<uuid>",
  "subproblem_id":"CUMCM-2022-A-Q1",
  "mmir_content":"<mmir-markdown>"
}'
```

### 9. confirm_subproblem_mmir — 确认 MMIR 版本（C1 预览）

确认一个不可变的 MMIR 版本，解锁执行。

```bash
modeling tool confirm_subproblem_mmir --project-root <path> --input '{
  "operation_id":"<uuid>",
  "project_id":"<uuid>",
  "subproblem_id":"CUMCM-2022-A-Q1",
  "revision":"<revision-hash>"
}'
```

### 10. export_subproblem — 导出子问题结果（C1 预览）

导出子问题的完整结果（需两次验证均 PASSED）。

```bash
modeling tool export_subproblem --project-root <path> --input '{
  "operation_id":"<uuid>",
  "project_id":"<uuid>",
  "subproblem_id":"CUMCM-2022-A-Q1"
}'
```

## 错误处理

所有工具在失败时返回非零退出码（1=建模错误，2=内部错误），错误信息以 JSON 格式输出到 STDERR。