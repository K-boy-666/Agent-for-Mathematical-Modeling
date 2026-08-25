# ADR 0001: 单发行物模块化单体

- Status: Accepted
- Date: 2026-07-17

## Context

M1 需要本地、可追踪的数学建模纵向切片，但没有第二部署单元或独立扩缩容需求。

## Decision

核心、能力、基础设施、CLI 和 MCP 保持一个 Python 发行物中的模块化单体，以导入边界隔离职责。
当前调用方是本地 CLI、STDIO MCP 和测试 Harness。

## Consequences

安装、版本和事务边界简单；模块边界必须由架构测试持续约束。未来拆分须有测得的部署需求和新 ADR。

## Rejected Alternatives

拒绝微服务、事件总线和多发行物，因为它们增加协议、部署与失败模式，却没有 M1 调用方。
