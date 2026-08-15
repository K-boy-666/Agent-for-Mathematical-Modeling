# Math Modeling MCP

本仓库是锁定 Python 3.11 环境的本地数学建模 MCP。
当前状态是 M1a 可运行纵向切片；不是生产就绪、1.0 兼容基线或 M1 完成。

## 开始

```powershell
uv sync --locked --group dev
uv run --locked --no-sync modeling bootstrap --project-root PATH
uv run --locked --no-sync modeling doctor --project-root PATH --deep --json
```

在 trusted project 中，把
[Codex 模板](docs/templates/codex/config.toml)复制为 `.codex/config.toml`。
它只连接六工具 STDIO MCP；核心不依赖 Codex。

## 验证

```powershell
uv run --locked --no-sync modeling verify --milestone m1a
```

M1a 只承诺 stable hash smoke only：固定向量与同环境重复执行一致；
完整 RFC 8785 符合性、跨平台门和 1.0 兼容基线属于 M1b。

## 文档

- [Context 与权威路由](docs/context/index.md)
- [M1 范围和阶段门](docs/product/m1-scope.md)
- [架构概览](docs/architecture/overview.md)
- [bootstrap 与 doctor](docs/operations/bootstrap-and-doctor.md)
- [M1a-0 历史可行性记录](spikes/m1a_0/README.md)

公开数据形状以打包 JSON Schema 为权威；`docs/contracts/` 只提供语义和源码路由。
