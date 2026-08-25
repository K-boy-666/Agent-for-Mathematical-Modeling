# ADR 0008: 单写者锁与启动恢复

- Status: Accepted
- Date: 2026-07-17

## Context

一个本地项目可能被两个进程同时打开，或在 Attempt、Validation、制品和幂等事务之间中断。

## Decision

每个项目使用一个可验证身份的单写者锁。生产组合在持锁后、服务前运行一次前 Session 恢复：
活动实体变为 `ABANDONED/server_recovery`，已提交终态不变，数学不自动重跑。当前调用方是
组合根、`SQLiteProjectStore`、RecoveryService 与 doctor。

## Consequences

并发写失败为有限可重试冲突；恢复确定且幂等。doctor 只读报告孤儿、暂存和不安全引用。

## Rejected Alternatives

拒绝多写者协调、自动重试数学、启动时删除未知文件和 doctor 自动修复；这些会损害可追踪性或数据安全。
