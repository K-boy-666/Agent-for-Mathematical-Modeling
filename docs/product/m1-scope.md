# M1 范围与阶段门

## 历史 M1a 承诺

M1a 交付本地 Python 3.11 单发行物中的可运行纵向切片：六工具 STDIO MCP、
SQLite 项目状态、一个显式求根能力、独立验证、doctor 和可复现 Harness。
完成声明必须来自当前源指纹对应的 M1a verify，必需跳过为零且 A-01–A-10 全有证据。

M1a 的哈希承诺是 stable hash smoke only：固定向量、默认值/空白规范化和同环境重复执行一致。
它不声明完整 RFC 8785 符合性、1.0 兼容基线、生产就绪或 M1 完成。

## 路线

`M1a-0R → A1–A12 → M1a Hard Gate → C1 → deferred M1b`

历史 M1a-0/M1a-0R 只证明官方 Codex 宿主能经真实 STDIO MCP 调用一次求根。
它不进入正式包，也不定义生产架构。

## M1a 预算

- 恰有 A1–A12 十二个顶层任务，最多四个有序工作包。
- 每个任务只有一个主要架构关注点和一个可验证增量。
- 不建立第二存储、执行后端、通用 DI、事件总线、队列、worker 池或 External Plugin SDK。
- 新抽象必须在批准计划中列出当前调用方与当前具体实现。

## M1b 当前基线

应用 `0.2.0`、公共契约 `1.0.0`、数据库 Schema `2`、完整 RFC 8785 向量、
内容寻址制品、崩溃恢复、故障注入和双平台门共同定义 M1b。
当前公开清单以 `TOOL_NAMES` 为准：原六工具加 C1 批准的四个预览工具。

## 权威来源

- [批准设计](../superpowers/specs/2026-07-16-math-modeling-mcp-design.md)
- [A12 接口决议](../superpowers/specs/2026-08-11-m1a-a12-interface-resolution.md)
- [M1 实施计划](../superpowers/plans/2026-07-17-math-modeling-mcp-m1.md)
