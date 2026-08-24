# M1b 发布验证

发布环境固定 Python `3.11` 与 uv `0.11.28`。锁文件是依赖版本权威；MCP 使用协议
`2025-11-25` 与 SDK 稳定 1.x。自动门、双平台证据和真实宿主烟测是三个不同层次。

## 自动 M1b 门

在干净或明确纳入指纹的源树执行：

```powershell
uv sync --locked --group dev
uv run --locked --no-sync modeling verify --milestone m1b
```

要求退出 0、required skips 为 0、A-01–A-10 与 B-01–B-10 全部 PASS、报告源指纹与当前文件一致。
结构化 JSON 与 Markdown 摘要原子发布到被忽略的 `build/verification/m1b/<fingerprint>`；
诊断脱敏、有界且不包含用户名、主机名、绝对路径或秘密。

## Windows 与 Ubuntu

同一提交必须在 `windows-latest` 和 `ubuntu-latest` 运行完全相同的上述 verify 命令。
CI 只授予 `contents: read`，不使用平台条件测试命令。Owning workflow 固定
`actions/checkout@v6`、`astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990`
（v8.3.2）和 `actions/upload-artifact@v7`；两份证据必须具有相同 commit、lock hash 和源指纹。

## 发布专用 Codex 烟测

自动门通过后，才在已信任项目中复制[Codex 模板](../templates/codex/config.toml)，由真实 Codex
经 MCP 完成黄金链；不得调用 shell 计算。宿主记录必须是原始平台产物，列出当前 `TOOL_NAMES`、
精确提交和有限工具调用，并由证据组装器复核数学 residual、状态、制品哈希与无 shell 条件。
这证明首宿主接入，不让 Codex 成为核心测试依赖，也不能替代 Windows/Ubuntu 自动证据。

发布包只有在三层证据精确绑定同一提交和源指纹、无必需 skip、无篡改且清单完整时才可声明 M1 完成。
