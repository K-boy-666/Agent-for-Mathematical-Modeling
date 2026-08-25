---
name: modeling-workflow
description: 完整数学建模工作流 — 从创建项目到导出结果
---

# 数学建模工作流

本 Skill 描述完整的数学建模工作流：创建项目 → 运行实验 → 验证结果 → 导出。

## 通用工作流

### 步骤 1：初始化项目

```bash
# 如果尚未初始化
modeling bootstrap --project-root <project-root>
```

### 步骤 2：健康检查

```bash
modeling tool health_check --project-root <project-root> --input '{}'
```

确认 `status: "OK"` 和 `ready_for_project_creation: true`。

### 步骤 3：创建项目

```bash
modeling tool create_project --project-root <project-root> --input '{
  "operation_id":"<generate-uuid>",
  "display_name":"我的数学建模项目"
}'
```

记录返回的 `project_id`。

### 步骤 4：查看可用能力

```bash
modeling tool list_capabilities --project-root <project-root> --input '{}'
```

### 步骤 5：运行实验

```bash
modeling tool run_experiment --project-root <project-root> --input '{
  "operation_id":"<generate-uuid>",
  "project_id":"<project-id>",
  "mode":"new",
  "capability":{"capability_id":"numerical.root_finding","contract_version":"0.1.0"},
  "payload":{"expression":"x**2 - 4","lower":0,"upper":3}
}'
```

记录返回的 `experiment_id` 和 `attempt_id`。

### 步骤 6：验证结果

```bash
modeling tool validate_experiment --project-root <project-root> --input '{
  "operation_id":"<generate-uuid>",
  "project_id":"<project-id>",
  "experiment_id":"<experiment-id>",
  "attempt_id":"<attempt-id>"
}'
```

### 步骤 7：查看项目状态

```bash
modeling tool get_project_status --project-root <project-root> --input '{
  "project_id":"<project-id>",
  "view":"summary"
}'
```

## CUMCM 竞赛工作流

对于 CUMCM 2022 A 题 Q1 等竞赛题目，使用完整工作流：

### 步骤 1-3：同上

### 步骤 4：注册题目资产

```bash
modeling tool register_problem_assets --project-root <project-root> --input '{
  "operation_id":"<uuid>",
  "project_id":"<project-id>",
  "assets":[
    {"label":"A题.pdf","path":"<absolute-path-to-A题.pdf>"},
    {"label":"附件3.xlsx","path":"<absolute-path-to-附件3.xlsx>"},
    {"label":"附件4.xlsx","path":"<absolute-path-to-附件4.xlsx>"},
    {"label":"result1-1.xlsx","path":"<absolute-path-to-result1-1.xlsx>"},
    {"label":"result1-2.xlsx","path":"<absolute-path-to-result1-2.xlsx>"}
  ]
}'
```

### 步骤 5：提交 MMIR

```bash
modeling tool put_subproblem_mmir --project-root <project-root> --input '{
  "operation_id":"<uuid>",
  "project_id":"<project-id>",
  "subproblem_id":"CUMCM-2022-A-Q1",
  "mmir_content":"# CUMCM 2022 A Q1 MMIR\n\n## 假设\n..."
}'
```

### 步骤 6：确认 MMIR

```bash
modeling tool confirm_subproblem_mmir --project-root <project-root> --input '{
  "operation_id":"<uuid>",
  "project_id":"<project-id>",
  "subproblem_id":"CUMCM-2022-A-Q1",
  "revision":"<revision-hash>"
}'
```

### 步骤 7-8：运行实验 + 验证（线性阻尼和幂律阻尼各一次）

### 步骤 9：导出结果

```bash
modeling tool export_subproblem --project-root <project-root> --input '{
  "operation_id":"<uuid>",
  "project_id":"<project-id>",
  "subproblem_id":"CUMCM-2022-A-Q1"
}'
```

## 注意事项

- 每个 `operation_id` 必须是唯一的 UUID，用于幂等性保证
- `project_id` 从 `create_project` 的返回值中获取
- 项目状态从 `STORAGE_READY` → `READY`（创建项目后）
- 所有 UUID 使用标准格式：`xxxxxxxx-xxxx-4xxx-xxxx-xxxxxxxxxxxx`
- 路径使用绝对路径