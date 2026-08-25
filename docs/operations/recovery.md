# 启动恢复与崩溃窗口

启动顺序固定为：验证项目身份与数据库 Schema `2`，取得单写者锁，生成当前 Session，执行一次
`recover_previous_session`，完成完整性检查，再对宿主提供服务。恢复不重新执行数学，也不猜测结果。

## 崩溃窗口与收敛

| 窗口 | 遗留状态 | 自动收敛 |
|---|---|---|
| 写入幂等记录前 | 无新记录 | 调用方可安全重试 |
| 已建立 `PENDING` / `IN_PROGRESS`，尚未运行 | 前一 Session 活动行 | Attempt 或 Validation 变为 `ABANDONED/server_recovery`，幂等记录完成 |
| 已进入 `RUNNING`，尚无终态 | 前一 Session 活动行 | 同上；绝不自动重跑 |
| 写暂存文件时中断 | `staging/` 中未知文件 | 保留并由 doctor 报警，不按名字盲删 |
| 制品已发布、数据库尚未引用 | 孤立制品 | 安全保留为孤立制品，doctor 报警 |
| 最终 SQLite 事务中断 | 全部提交或全部回滚 | 回滚时按前述活动状态恢复；提交时正常重放 |
| 数据库已提交、响应尚未返回 | 完整终态和幂等结果 | 相同 `operation_id` 返回同一已提交实体 |
| 已引用制品丢失、篡改或错型 | 不安全引用 | 项目进入退化视图，读/重放失败关闭为完整性错误 |

终态 `SUCCEEDED`、`NUMERICAL_FAILURE`、`ERRORED`、`TIMED_OUT`、`ABANDONED` 不被恢复重写。
Validation 的 `SUCCEEDED` 与数学 outcome 分开保存；恢复不能把 `FAILED` 变成运行错误。

## 运维边界

```powershell
uv run --locked --no-sync modeling doctor --project-root PATH --deep --json
```

doctor 只从受控只读快照报告恢复状态、孤立制品、暂存文件、输入漂移和引用完整性。
它不修复、不迁移、不删除、不重新执行能力。任何手工数据库编辑、文件替换或孤立清理都不属于
M1 支持流程；应先复制项目作取证，再由拥有该格式的后续迁移工具处理。

事务顺序见[状态模型](../architecture/state-model.md)，安全检查见[安全边界](../architecture/security.md)。
