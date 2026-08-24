# ADR 0003: SQLite 与内容寻址制品

- Status: Accepted
- Date: 2026-07-17

## Context

结构化关系适合事务数据库，大型结果与报告必须可验证且不能使 SQLite 成为无界 blob 容器。

## Decision

`SQLiteProjectStore` 拥有数据库 Schema `2`；`FileSystemArtifactStore` 把规范 JSON 按 SHA-256
写到受管路径。应用先发布文件，再在一个事务中提交制品元数据、实体终态和幂等引用。
当前调用方是运行、验证、状态读取、doctor 与恢复用例。

## Consequences

引用可验证且崩溃只会产生安全孤儿；运维必须同时检查数据库关系与制品字节。

## Rejected Alternatives

拒绝数据库 blob、任意用户输出路径、远程对象存储和第二持久化端口；M1 不需要这些部署复杂度。
