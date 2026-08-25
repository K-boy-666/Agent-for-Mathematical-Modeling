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

## 候选提交与 CI 证据

先提交候选，再从该提交的 workflow 下载一份 Windows 和一份 Ubuntu `verification-report.json`；
两份报告必须是 `m1b-verification-report/1.0.0`，并具有相同的完整 `commit`、
`source_fingerprint` 和 lock hash。报告所在目录须保留 verify 原子发布的全部七个文件，不能只复制
JSON 报告。任何源文件、配置、文档或测试变更都会形成新候选，旧 CI 与宿主记录不得混用。

## Codex CLI 原始记录

在该提交的临时可信 checkout 中使用签入模板和真实 Codex CLI。烟测只能调用 `modeling` MCP，
工具调用集合必须精确等于当前 `TOOL_NAMES`，且至少包含一次成功的根求解与独立 residual 验证；
不得出现 shell、命令执行或其他工具。`register_problem_assets` 可读取 checkout 内现有的相对路径测试
语料，随后以同一项目完成 MMIR 写入、确认和导出。保存 `codex exec --ephemeral --json` 的原始
JSONL；组装器会校验官方 `thread.started`/`item.completed` 记录并只写入脱敏后的工具元数据、
独立重算 residual、结果哈希和验证报告哈希。

## 组装与复核

```powershell
uv run --locked --no-sync modeling evidence assemble `
  --windows-report WINDOWS/verification-report.json `
  --ubuntu-report UBUNTU/verification-report.json `
  --codex-transcript codex-transcript.jsonl `
  --destination build/release-evidence/COMMIT

uv run --locked --no-sync modeling evidence validate `
  --bundle build/release-evidence/COMMIT `
  --source-fingerprint sha256:FINGERPRINT
```

组装不联网、不调用 GitHub、不启动 Codex，也不更新基线。它只接受两个平台全 PASS、0 skip、
A-01–B-10 完整、当前检查 profile 完整、Codex 工具集合完整且制品哈希一致的输入；所有 JSON
规范化后写入同级 staging 目录，清单最后写入并原子发布。validate 重新计算每个 payload 的
SHA-256，并复核提交、指纹、平台、验收映射、黄金数学结果与四方制品哈希关系。
