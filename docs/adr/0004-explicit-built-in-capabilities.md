# ADR 0004: 显式 Built-in Capability

- Status: Accepted
- Date: 2026-07-17

## Context

数学能力需要自描述和可扩展，但 M1 只执行随发行物审查、测试并信任的实现。

## Decision

每个 Built-in Capability 自带描述符、版本化 Schema、实现、独立 Validator、测试与局部 context；
唯一组合根逐项注册后封存注册表。当前调用方是 `ModelingApplication` 与 `list_capabilities`。

## Consequences

能力边界可审计，新增能力需要显式代码变更和 focused verify。Built-in Capability 不是 External Plugin。

## Rejected Alternatives

拒绝动态扫描、entry point、安装市场、权限框架和 External Plugin SDK；没有第三方安装需求。
