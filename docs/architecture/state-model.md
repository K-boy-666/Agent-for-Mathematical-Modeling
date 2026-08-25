# 状态与事务模型

应用 `0.2.0` 使用数据库 Schema `2`。`.modeling/project.json` 与 SQLite 身份必须一致；
状态只能由拥有该状态的基础设施写入。

## Project

- `UNINITIALIZED → STORAGE_READY`：bootstrap 原子建立受管目录与 SQLite，不创建领域 Project。
- `STORAGE_READY → READY`：`create_project` 创建唯一 Project。
- `READY → DEGRADED`：只在启动或完整性检查发现不安全状态时呈现；doctor 不执行转换或修复。

## Attempt

- `PENDING → RUNNING`
- `RUNNING → SUCCEEDED`
- `RUNNING → NUMERICAL_FAILURE`
- `RUNNING → ERRORED`
- `RUNNING → TIMED_OUT`
- `RUNNING → ABANDONED`

终态不可再次转换。数值失败是实体结果，不是系统错误；`TIMED_OUT` 与 `ABANDONED` 只携带稳定终止原因。

## Validation

- `PENDING → RUNNING`
- `RUNNING → SUCCEEDED`，并单独记录 `PASSED`、`FAILED` 或 `INCONCLUSIVE` outcome。
- `RUNNING → ERRORED`
- `RUNNING → TIMED_OUT`
- `RUNNING → ABANDONED`

Validation 只读取已成功且经哈希验证的结果。求解成功不能替代 Validation `PASSED`。

## 幂等与提交顺序

写操作键是 `(scope_id, tool_name, operation_id)`，并保存 `canonical_request_hash`。
同键同哈希返回已提交结果；同键异哈希返回冲突；`IN_PROGRESS` 不伪装为完成。

稳定结果和报告遵守“先发布文件，再提交引用”：规范 JSON 写入同文件系统暂存文件，刷新、原子改名到
内容寻址路径，再在一个 SQLite 事务中写 Artifact 元数据、实体终态和幂等完成记录。事务失败留下的文件是
安全孤儿；数据库绝不引用未发布文件。单调 deadline 在制品发布后、最终事务前再次检查。

恢复规则见[恢复手册](../operations/recovery.md)，数据形状见[MCP tools v1](../contracts/mcp-tools-v1.md)。
