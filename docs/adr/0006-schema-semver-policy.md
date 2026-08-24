# ADR 0006: JSON Schema 与独立 SemVer 轴

- Status: Accepted
- Date: 2026-07-17

## Context

应用、MCP 协议、工具、能力、实现、策略、报告和数据库会以不同速度演进。

## Decision

JSON Schema Draft 2020-12 是跨边界数据形状权威；各版本轴独立采用 SemVer，稳定 1.0 基线由
旧语料和兼容测试保护。当前调用方是 MCP 适配器、能力注册表、持久化、Harness 和发布审查。

## Consequences

语义变化必须同步 Schema、DTO、语料、文档和测试；实现 patch 不必制造无关契约版本。

## Rejected Alternatives

拒绝单一全局版本、仅靠 Pydantic 生成 Schema、自动更新 Snapshot 和宽松未知字段处理。
