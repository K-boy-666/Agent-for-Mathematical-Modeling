# Math Modeling MCP

本仓库是锁定 Python 3.11 环境的本地数学建模 MCP。
当前稳定基线是应用 `0.2.0`、MCP 协议 `2025-11-25`、公共契约 `1.0.0`
和数据库 Schema `2`；它是可信的本地 M1 基线，不是多用户生产服务。

## 开始

```powershell
uv sync --locked --group dev
uv run --locked --no-sync modeling bootstrap --project-root PATH
uv run --locked --no-sync modeling doctor --project-root PATH --deep --json
```

在 trusted project 中，把
[Codex 模板](docs/templates/codex/config.toml)复制为 `.codex/config.toml`。
它只连接当前 `TOOL_NAMES` 定义的十工具 STDIO MCP；核心不依赖 Codex。

## 验证

```powershell
uv run --locked --no-sync modeling verify --milestone m1b
```

完成声明要求 Windows 与 Ubuntu 对同一提交运行上述命令，退出 0 且必需跳过为 0；
发布时再附加真实 Codex 宿主烟测。局部能力验证可运行
`uv run --locked --no-sync modeling verify --capability numerical.root_finding`。
历史 M1a 承诺仍只是 stable hash smoke only，不等于当前完整 RFC 8785 基线。

## 文档

- [Context 与权威路由](docs/context/index.md)
- [产品愿景与路线](docs/product/vision.md)
- [架构概览](docs/architecture/overview.md)
- [MCP tools 1.0 契约](docs/contracts/mcp-tools-v1.md)
- [恢复手册](docs/operations/recovery.md)
- [发布验证](docs/operations/release-verification.md)
- [M1a-0 历史可行性记录](spikes/m1a_0/README.md)

公开数据形状以打包 JSON Schema 为权威；`docs/contracts/` 只提供语义和源码路由。
