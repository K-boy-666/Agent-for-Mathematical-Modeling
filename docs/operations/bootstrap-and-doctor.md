# bootstrap 与 doctor

## 建立项目状态

在预先创建的项目目录运行：

```powershell
uv run --locked --no-sync modeling bootstrap --project-root PATH
```

首次调用建立 `.modeling/` 权威状态；重复调用幂等。
不要覆盖已有但身份不明的目录，也不要提交本地 `.modeling/`。

## 只读诊断

```powershell
uv run --locked --no-sync modeling doctor --project-root PATH --json
uv run --locked --no-sync modeling doctor --project-root PATH --deep --json
```

doctor 从受控只读快照诊断，不修复、不迁移、不写权威状态。
普通模式检查状态、Schema、注册表和 SQLite 完整性；deep 增加独立锁与真实求根烟测。
退出码：0 就绪，1 警告，2 不安全或退化。JSON 输出版本化、脱敏且不含绝对路径。

## Codex 项目配置

[仓库模板](../templates/codex/config.toml)必须只复制到已信任项目的 `.codex/config.toml`。
它只是 MCP 宿主适配配置，不是核心依赖。模板使用锁定、离线的 `uv run --locked --no-sync`，
固定六工具、10 秒启动超时和 65 秒工具超时。

## M1a 完整验证

```powershell
uv run --locked --no-sync modeling verify --milestone m1a
```

完成声明要求退出 0、必需跳过 0、当前源指纹一致且 A-01–A-10 全部 PASS。
证据写入被忽略的 `build/verification/`；它不是项目权威状态。

边界细节以 [A12 接口决议](../superpowers/specs/2026-08-11-m1a-a12-interface-resolution.md)为准。
