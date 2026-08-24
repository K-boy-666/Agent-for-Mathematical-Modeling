---
name: release-verification
description: Use when producing or checking M1b cross-platform reports, an exact-commit CI run, a Codex host smoke, a release evidence bundle, or a completion claim.
---

# Release Verification

## Overview

发布证据必须绑定同一候选提交和源指纹；本地成功不能替代真实双平台与宿主证据。

## Procedure

1. 在干净候选提交上新鲜运行 M1a、M1b 和打包门；任何源修改都使后续证据失效。
2. 推送精确候选提交，取得同一次 CI 矩阵的真实 Windows 与 Ubuntu 报告。拒绝复制、改写或用本地报告冒充另一平台。
3. 按报告内容核对：commit 与 source fingerprint 完全相同、milestone 为 M1b、平台各一、全部必需检查 PASS、required skips 为零。
4. 从该提交创建一次性 checkout，复制项目 Codex 模板；由用户通过正常控制显式信任。不得自动修改全局 trust。
5. Codex 只使用 modeling MCP，禁止 shell。以 `modeling_core.contracts.tools.TOOL_NAMES` 为当前工具集合并调用每个工具；不得沿用历史工具数量。
6. 只把验证过、限长且脱敏的 transcript 与报告交给 assembler；拒绝原始环境、绝对路径、秘密和未验证字节。组装后重新计算每个 hash 并运行 validator。
7. 最后重跑 M1a、M1b、bundle validator 和 clean-tree 检查；任一失败都停止完成声明。

## Verification

```powershell
uv run --locked --no-sync modeling verify --milestone m1a
uv run --locked --no-sync modeling verify --milestone m1b
uv run --locked --no-sync modeling evidence validate --bundle <bundle> --source-fingerprint <sha256>
```

## References

- [B11–B12 实施门](../../../docs/superpowers/plans/2026-07-17-math-modeling-mcp-m1.md)
- [证据实现](../../../src/modeling_harness/evidence.py)
- [Codex 项目模板](../../../docs/templates/codex/config.toml)
- [Context 索引](../../../docs/context/index.md)

## Red flags

- 两份报告来自不同 commit 或 fingerprint
- required skip 非零
- 复制平台报告或只看 CI conclusion
- Codex transcript 包含 shell、少调用当前工具或自动改 trust
- bundle 含原始环境、路径、秘密或未验证 transcript

出现任一项都不得组装或宣称完成。
