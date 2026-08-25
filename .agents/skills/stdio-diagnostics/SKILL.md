---
name: stdio-diagnostics
description: Use when an MCP STDIO handshake, frame parser, subprocess shutdown, Windows handle, protocol-purity, timeout, or stderr diagnostic fails or hangs.
---

# STDIO Diagnostics

## Overview

STDOUT 是协议传输，不是日志流。诊断必须保持帧纯净、生命周期有界且输出脱敏。

## Procedure

1. 先用真实 MCP 客户端和子进程复现；记录握手、调用、关闭中的具体失败阶段，不加重试或长 `sleep`。
2. 以参数数组启动进程，保持 `shell=False`；STDOUT 与 STDERR 分开捕获。
3. 逐帧检查 STDOUT：UTF-8、无 BOM、换行终止、合法 JSON-RPC。任何非协议字节都视为产品缺陷。
4. 日志只写 STDERR，并只含稳定错误码、阶段、退出码、耗时和关联 ID。禁止原始请求、完整命令、环境值、绝对路径、异常原文或 traceback。
5. 异常路径按拥有关系关闭 ClientSession、管道和 composition；Windows 还要等待整个 Job Object 进程树并关闭观察句柄。使用单个有界截止时间，超时即失败。
6. 验证 writer lease 可重新获取，且失败诊断有限、脱敏、不进入权威项目状态。

## Verification

B9–B12 必须原样运行下面两条命令；测试文件名中的 `m1a` 是历史归属，
不得据此把最终 `m1b` 门替换为旧里程碑。

```powershell
uv run --locked --no-sync pytest tests/integration/test_stdio_golden_m1a.py tests/security/test_m1a_boundaries.py -q
uv run --locked --no-sync modeling verify --milestone m1b
```

## References

- [MCP 目录规则](../../../src/modeling_mcp/AGENTS.md)
- [严格 STDIO 传输](../../../src/modeling_mcp/strict_stdio.py)
- [真实黄金链路](../../../tests/integration/test_stdio_golden_m1a.py)
- [测试边界](../../../tests/AGENTS.md)

## Common mistakes

| symptom | correction |
|---|---|
| 用 stdout 打印调试信息 | 写有限、脱敏的 STDERR 诊断 |
| 挂住后增加重试和 sleep | 找到未关闭的管道、进程、锁或句柄 |
| 合并 stdout/stderr | 分流并单独验证协议纯净性 |
| 回显原始流或 traceback | 只保留 allowlisted 诊断字段 |
