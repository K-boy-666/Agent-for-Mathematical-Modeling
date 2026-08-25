# ADR 0005: 本地 STDIO MCP

- Status: Accepted
- Date: 2026-07-17

## Context

首个宿主需要标准工具协议，但本地项目不需要监听端口、账户系统或远程服务面。

## Decision

使用 MCP 协议 `2025-11-25` 的本地 STDIO transport；`modeling_mcp` 只做 Schema、DTO、
门面调用和错误映射。当前调用方是 Codex 薄适配配置与通用 MCP 客户端测试。

## Consequences

STDOUT 必须只有协议帧，日志写 STDERR；进程生命周期和句柄关闭成为跨平台门禁。

## Rejected Alternatives

拒绝 HTTP 服务、宿主 SDK 嵌入、MCP Prompt/Resource/Sampling 和自定义 RPC；M1 无远程或专属宿主需求。
